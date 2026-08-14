"""Ingestion pipeline (PRD §6.2): discover → fetch → normalize → validate → promote.

Flow classification rules (versioned config, PRD §3):
- Spring with >=3 discharge measurements across >=2 hydro-years, median >= 5 L/s,
  snapped within 500 m => VERIFIED_PERENNIAL (0.75, 180 d validity).
- Spring measured within the last 6 years with q >= 1 L/s => VERIFIED_CURRENT
  (0.65, 90 d validity).
- Active hydrometric station within 500 m => VERIFIED_CURRENT (0.7, 120 d).
- OSM intermittent=yes and no official upgrade => SEASONAL_EXPECTED (0.5).
- Otherwise UNKNOWN.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from pyproj import Transformer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from goldflow.domain.hydrology import FlowStatus
from goldflow.domain.results import Err, Ok, Result
from goldflow.domain.values import AuthorityClass, SourceId, utc_now
from goldflow.infrastructure.db.models import (
    GeologicalUnitRow,
    SpringRow,
    StructuralFeatureRow,
    WaterwayRow,
    WaterwaySegmentRow,
)
from goldflow.infrastructure.db.repositories import SourceRepository
from goldflow.infrastructure.gsi import ATTRIBUTION as GSI_ATTRIBUTION
from goldflow.infrastructure.gsi import GsiArcGisAdapter
from goldflow.infrastructure.osm import ATTRIBUTION as OSM_ATTRIBUTION
from goldflow.infrastructure.osm import OverpassAdapter
from goldflow.infrastructure.water_authority import (
    SpringDischargeRecord,
    WaterAuthorityAdapter,
)

_TO_ITM = Transformer.from_crs(4326, 2039, always_xy=True)

PERENNIAL_MIN_MEASUREMENTS = 3
PERENNIAL_MIN_YEARS = 2
PERENNIAL_MIN_MEDIAN_LPS = 5.0
CURRENT_MIN_LPS = 1.0
CURRENT_MAX_AGE_YEARS = 6
SNAP_RADIUS_M = 500.0


@dataclass(frozen=True, slots=True)
class IngestionReport:
    segments: int
    springs: int
    stations: int
    geology_units: int
    faults: int
    flow_upgraded_segments: int
    sources: dict[str, str]


def _parse_ddmmyyyy(raw: str) -> datetime | None:
    try:
        day, month, year = raw.strip().split(" ")[0].split("/")
        return datetime(int(year), int(month), int(day), tzinfo=utc_now().tzinfo)
    except (ValueError, AttributeError):
        return None


def _classify_spring(
    discharges: tuple[SpringDischargeRecord, ...], now: datetime
) -> tuple[FlowStatus, float, timedelta] | None:
    """Pure classification of a spring's flow regime from its discharge history."""
    if not discharges:
        return None
    values = [d.discharge_lps for d in discharges]
    years = {d.hydro_year for d in discharges}
    dated = [(d, _parse_ddmmyyyy(d.measured_on)) for d in discharges]
    recent = [
        d
        for d, when in dated
        if when is not None and (now - when).days <= CURRENT_MAX_AGE_YEARS * 365
    ]
    if (
        len(discharges) >= PERENNIAL_MIN_MEASUREMENTS
        and len(years) >= PERENNIAL_MIN_YEARS
        and statistics.median(values) >= PERENNIAL_MIN_MEDIAN_LPS
    ):
        return (FlowStatus.VERIFIED_PERENNIAL, 0.75, timedelta(days=180))
    if any(d.discharge_lps >= CURRENT_MIN_LPS for d in recent):
        return (FlowStatus.VERIFIED_CURRENT, 0.65, timedelta(days=90))
    return None


class IngestionService:
    def __init__(
        self,
        session: AsyncSession,
        osm: OverpassAdapter,
        water: WaterAuthorityAdapter,
        gsi: GsiArcGisAdapter,
    ) -> None:
        self._session = session
        self._osm = osm
        self._water = water
        self._gsi = gsi
        self._sources = SourceRepository(session)

    async def ingest_pilot(
        self, bbox_4326: tuple[float, float, float, float]
    ) -> Result[IngestionReport, object]:
        sources: dict[str, str] = {}

        osm_source = await self._sources.upsert_by_url(
            name="OpenStreetMap waterways (Overpass)",
            kind="vector",
            authority_class=AuthorityClass.SECONDARY,
            url="https://overpass-api.de/api/interpreter#waterways",
            retrieval_method="overpass",
            license_text=f"ODbL — {OSM_ATTRIBUTION}",
        )
        water_source = await self._sources.upsert_by_url(
            name="Israel Water Authority — springs, discharge, hydrometric stations",
            kind="tabular",
            authority_class=AuthorityClass.AUTHORITATIVE,
            url="https://data.gov.il/dataset/springs",
            retrieval_method="ckan-datastore",
            license_text="data.gov.il open data",
        )
        gsi_source = await self._sources.upsert_by_url(
            name="GSI 1:200,000 geological map (2014)",
            kind="arcgis-feature",
            authority_class=AuthorityClass.AUTHORITATIVE,
            url="https://egozi.gsi.gov.il/arcgis/rest/services/Hosted/Israel_200000_2014_geology",
            retrieval_method="arcgis-rest",
            license_text=GSI_ATTRIBUTION,
        )
        match (osm_source, water_source, gsi_source):
            case (Ok(osm_id), Ok(water_id), Ok(gsi_id)):
                sources["osm"] = str(osm_id)
                sources["water_authority"] = str(water_id)
                sources["gsi"] = str(gsi_id)
            case _:
                first_err = next(
                    r for r in (osm_source, water_source, gsi_source) if isinstance(r, Err)
                )
                return Err(first_err.error)

        segments = await self._ingest_waterways(bbox_4326, osm_id)
        springs = await self._ingest_springs(water_id, bbox_4326)
        stations = await self._ingest_stations(bbox_4326)
        geology_units, faults = await self._ingest_geology(bbox_4326, gsi_id)
        upgraded = await self._classify_segment_flow()
        await self._session.commit()
        return Ok(
            IngestionReport(
                segments=segments,
                springs=springs,
                stations=stations,
                geology_units=geology_units,
                faults=faults,
                flow_upgraded_segments=upgraded,
                sources=sources,
            )
        )

    async def _ingest_waterways(
        self, bbox: tuple[float, float, float, float], source_id: SourceId
    ) -> int:
        result = await self._osm.waterways(bbox)
        match result:
            case Err():
                return 0
            case Ok(ways):
                pass
        count = 0
        for way in ways:
            coords_itm = [_TO_ITM.transform(lon, lat) for lon, lat in way.coords_4326]
            if len(coords_itm) < 2:
                continue
            wkt_points = ", ".join(f"{x:.2f} {y:.2f}" for x, y in coords_itm)
            length = sum(
                (
                    (coords_itm[i + 1][0] - coords_itm[i][0]) ** 2
                    + (coords_itm[i + 1][1] - coords_itm[i][1]) ** 2
                )
                ** 0.5
                for i in range(len(coords_itm) - 1)
            )
            existing = await self._session.execute(
                text(
                    "SELECT id FROM core.waterway_segment WHERE source_feature_ref = :ref"
                ),
                {"ref": f"osm-way/{way.way_id}"},
            )
            if existing.scalar_one_or_none() is not None:
                continue
            waterway = WaterwayRow(id=uuid4(), name=way.name, name_he=way.name)
            self._session.add(waterway)
            initial_status = (
                FlowStatus.SEASONAL_EXPECTED if way.intermittent else FlowStatus.UNKNOWN
            )
            self._session.add(
                WaterwaySegmentRow(
                    id=uuid4(),
                    waterway_id=waterway.id,
                    name=way.name,
                    geom=f"SRID=2039;LINESTRING({wkt_points})",
                    flow_status=initial_status.value,
                    flow_confidence=0.5 if way.intermittent else 0.0,
                    length_m=length,
                    source_id=source_id,
                    source_feature_ref=f"osm-way/{way.way_id}",
                )
            )
            count += 1
        await self._session.flush()
        return count

    async def _ingest_springs(
        self, source_id: SourceId, bbox: tuple[float, float, float, float]
    ) -> int:
        springs_result = await self._water.springs()
        discharges_result = await self._water.spring_discharges()
        match (springs_result, discharges_result):
            case (Ok(springs), Ok(discharges)):
                pass
            case _:
                return 0
        min_x, min_y = _TO_ITM.transform(bbox[0], bbox[1])
        max_x, max_y = _TO_ITM.transform(bbox[2], bbox[3])
        by_spring: dict[int, list[SpringDischargeRecord]] = {}
        for discharge in discharges:
            by_spring.setdefault(discharge.spring_id, []).append(discharge)
        count = 0
        now = utc_now()
        for spring in springs:
            if not (min_x <= spring.x_itm <= max_x and min_y <= spring.y_itm <= max_y):
                continue
            history = tuple(by_spring.get(spring.spring_id, ()))
            latest_q: float | None = None
            latest_when: datetime | None = None
            for record in history:
                when = _parse_ddmmyyyy(record.measured_on)
                if when is not None and (latest_when is None or when > latest_when):
                    latest_when = when
                    latest_q = record.discharge_lps
            existing = await self._session.execute(
                text("SELECT id FROM core.spring WHERE source_feature_ref = :ref"),
                {"ref": f"spring/{spring.spring_id}"},
            )
            if existing.scalar_one_or_none() is not None:
                continue
            self._session.add(
                SpringRow(
                    id=uuid4(),
                    name=spring.name,
                    geom=f"SRID=2039;POINT({spring.x_itm} {spring.y_itm})",
                    discharge_lps=latest_q,
                    observed_at=latest_when,
                    source_id=source_id,
                    source_feature_ref=f"spring/{spring.spring_id}",
                )
            )
            classification = _classify_spring(history, now)
            if classification is not None:
                status, confidence, validity = classification
                await self._session.execute(
                    text(
                        """
                        UPDATE core.waterway_segment ws SET
                            flow_status = :status,
                            flow_confidence = GREATEST(ws.flow_confidence, :conf),
                            flow_valid_until = :valid_until
                        WHERE ST_DWithin(ws.geom,
                              ST_SetSRID(ST_MakePoint(:x, :y), 2039), :radius)
                          AND ws.flow_status NOT IN ('VERIFIED_PERENNIAL')
                        """
                    ),
                    {
                        "status": status.value,
                        "conf": confidence,
                        "valid_until": now + validity,
                        "x": spring.x_itm,
                        "y": spring.y_itm,
                        "radius": SNAP_RADIUS_M,
                    },
                )
            count += 1
        await self._session.flush()
        return count

    async def _ingest_stations(self, bbox: tuple[float, float, float, float]) -> int:
        result = await self._water.hydro_stations()
        match result:
            case Err():
                return 0
            case Ok(stations):
                pass
        min_x, min_y = _TO_ITM.transform(bbox[0], bbox[1])
        max_x, max_y = _TO_ITM.transform(bbox[2], bbox[3])
        now = utc_now()
        count = 0
        for station in stations:
            if not (min_x <= station.x_itm <= max_x and min_y <= station.y_itm <= max_y):
                continue
            count += 1
            if not station.active:
                continue
            await self._session.execute(
                text(
                    """
                    UPDATE core.waterway_segment ws SET
                        flow_status = CASE
                            WHEN ws.flow_status = 'VERIFIED_PERENNIAL'
                            THEN ws.flow_status ELSE 'VERIFIED_CURRENT' END,
                        flow_confidence = GREATEST(ws.flow_confidence, 0.7),
                        flow_valid_until = COALESCE(ws.flow_valid_until, :valid_until)
                    WHERE ST_DWithin(ws.geom,
                          ST_SetSRID(ST_MakePoint(:x, :y), 2039), :radius)
                    """
                ),
                {
                    "valid_until": now + timedelta(days=120),
                    "x": station.x_itm,
                    "y": station.y_itm,
                    "radius": SNAP_RADIUS_M,
                },
            )
        await self._session.flush()
        return count

    async def _ingest_geology(
        self, bbox: tuple[float, float, float, float], source_id: SourceId
    ) -> tuple[int, int]:
        units = 0
        faults = 0
        formations = await self._gsi.query_layer(5, bbox_4326=bbox)
        match formations:
            case Ok(features):
                for feature in features:
                    geometry = feature.geometry
                    if geometry.get("type") not in ("Polygon", "MultiPolygon"):
                        continue
                    existing = await self._session.execute(
                        text("SELECT id FROM core.geological_unit WHERE unit_ref = :ref"),
                        {"ref": f"gsi-formation/{feature.feature_ref}"},
                    )
                    if existing.scalar_one_or_none() is not None:
                        continue
                    rings = (
                        geometry["coordinates"]
                        if geometry["type"] == "MultiPolygon"
                        else [geometry["coordinates"]]
                    )
                    polygons_itm: list[str] = []
                    for polygon in rings:
                        ring_texts: list[str] = []
                        for ring in polygon:
                            pts = [_TO_ITM.transform(lon, lat) for lon, lat in ring]
                            if len(pts) < 4:
                                continue
                            ring_texts.append(
                                "(" + ", ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + ")"
                            )
                        if ring_texts:
                            polygons_itm.append("(" + ", ".join(ring_texts) + ")")
                    if not polygons_itm:
                        continue
                    description = str(
                        feature.properties.get("name_eng")
                        or feature.properties.get("name_heb")
                        or ""
                    )
                    self._session.add(
                        GeologicalUnitRow(
                            id=uuid4(),
                            unit_ref=f"gsi-formation/{feature.feature_ref}",
                            description=description,
                            lithology=description,
                            age=str(feature.properties.get("code") or ""),
                            geom="SRID=2039;MULTIPOLYGON(" + ", ".join(polygons_itm) + ")",
                            source_id=source_id,
                        )
                    )
                    units += 1
            case Err():
                pass
        fault_features = await self._gsi.query_layer(0, bbox_4326=bbox)
        match fault_features:
            case Ok(features):
                for feature in features:
                    geometry = feature.geometry
                    if geometry.get("type") not in ("LineString", "MultiLineString"):
                        continue
                    existing = await self._session.execute(
                        text(
                            "SELECT id FROM core.structural_feature "
                            "WHERE source_feature_ref = :ref"
                        ),
                        {"ref": f"gsi-fault/{feature.feature_ref}"},
                    )
                    if existing.scalar_one_or_none() is not None:
                        continue
                    lines = (
                        geometry["coordinates"]
                        if geometry["type"] == "MultiLineString"
                        else [geometry["coordinates"]]
                    )
                    line_texts: list[str] = []
                    for line in lines:
                        pts = [_TO_ITM.transform(lon, lat) for lon, lat in line]
                        if len(pts) < 2:
                            continue
                        line_texts.append(
                            "(" + ", ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + ")"
                        )
                    if not line_texts:
                        continue
                    self._session.add(
                        StructuralFeatureRow(
                            id=uuid4(),
                            kind="FAULT",
                            name=None,
                            geom="SRID=2039;MULTILINESTRING(" + ", ".join(line_texts) + ")",
                            source_id=source_id,
                            source_feature_ref=f"gsi-fault/{feature.feature_ref}",
                        )
                    )
                    faults += 1
            case Err():
                pass
        await self._session.flush()
        return units, faults

    async def _classify_segment_flow(self) -> int:
        """Validate geometries and count segments carrying verified flow."""
        await self._session.execute(
            text(
                "UPDATE core.waterway_segment SET geom = ST_MakeValid(geom) "
                "WHERE NOT ST_IsValid(geom)"
            )
        )
        await self._session.execute(
            text(
                "UPDATE core.geological_unit SET geom = ST_CollectionExtract("
                "ST_MakeValid(geom), 3) WHERE NOT ST_IsValid(geom)"
            )
        )
        result = await self._session.execute(
            text(
                "SELECT COUNT(*) FROM core.waterway_segment "
                "WHERE flow_status IN ('VERIFIED_PERENNIAL','VERIFIED_CURRENT')"
            )
        )
        return int(result.scalar_one() or 0)
