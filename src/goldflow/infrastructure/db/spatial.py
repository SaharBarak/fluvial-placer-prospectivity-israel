"""Spatial query service: PostGIS joins whose results feed the pure core.

Upstream tracing follows segment topology via a recursive CTE: a segment B is
upstream of A when B's downstream endpoint lies within snap tolerance of A's
upstream endpoint. Heuristic MVP topology per PRD §13.2 with method flagged.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from goldflow.domain.geology import UpstreamLithology
from goldflow.domain.results import DatabaseError, Err, Ok, Result
from goldflow.domain.values import Meters, WaterwaySegmentId

SNAP_TOLERANCE_M = 150.0
UPSTREAM_MAX_DEPTH = 12
UPSTREAM_BUFFER_M = 1500.0
CONFLUENCE_RADIUS_M = 300.0


@dataclass(frozen=True, slots=True)
class SegmentSpatialFacts:
    upstream_lithologies: tuple[UpstreamLithology, ...]
    nearest_fault_distance: Meters | None
    upstream_length_m: float
    confluence_count: int
    sinuosity: float | None
    water_quality_alert_nearby: bool


_UPSTREAM_CTE = """
WITH RECURSIVE seg AS (
    SELECT id, geom, length_m, 0 AS depth
    FROM core.waterway_segment WHERE id = :segment_id
    UNION ALL
    SELECT ws.id, ws.geom, ws.length_m, seg.depth + 1
    FROM core.waterway_segment ws
    JOIN seg ON ST_DWithin(ST_EndPoint(ws.geom), ST_StartPoint(seg.geom), :snap)
    WHERE ws.id != seg.id AND seg.depth < :max_depth
)
"""


class SpatialQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def facts_for_segment(
        self, segment_id: WaterwaySegmentId
    ) -> Result[SegmentSpatialFacts, DatabaseError]:
        try:
            upstream = await self._session.execute(
                text(
                    _UPSTREAM_CTE
                    + """
                    SELECT COALESCE(SUM(length_m), 0) AS total_len,
                           COUNT(*) - 1 AS upstream_count
                    FROM (SELECT DISTINCT id, length_m FROM seg) d
                    """
                ),
                {
                    "segment_id": str(segment_id),
                    "snap": SNAP_TOLERANCE_M,
                    "max_depth": UPSTREAM_MAX_DEPTH,
                },
            )
            upstream_row = upstream.one()
            upstream_length = float(upstream_row.total_len or 0.0)

            lith = await self._session.execute(
                text(
                    _UPSTREAM_CTE
                    + """
                    , zone AS (
                        SELECT ST_Buffer(ST_Collect(DISTINCT geom), :buffer) AS g FROM seg
                    )
                    SELECT gu.unit_ref, gu.description,
                           SUM(ST_Area(ST_Intersection(gu.geom, zone.g))) AS ix_area,
                           (SELECT ST_Area(g) FROM zone) AS zone_area
                    FROM core.geological_unit gu, zone
                    WHERE ST_Intersects(gu.geom, zone.g)
                    GROUP BY gu.unit_ref, gu.description
                    ORDER BY ix_area DESC
                    LIMIT 12
                    """
                ),
                {
                    "segment_id": str(segment_id),
                    "snap": SNAP_TOLERANCE_M,
                    "max_depth": UPSTREAM_MAX_DEPTH,
                    "buffer": UPSTREAM_BUFFER_M,
                },
            )
            lithologies: list[UpstreamLithology] = []
            for row in lith:
                zone_area = float(row.zone_area or 0.0)
                if zone_area <= 0:
                    continue
                lithologies.append(
                    UpstreamLithology(
                        unit_reference=str(row.unit_ref),
                        description=str(row.description or ""),
                        area_fraction=min(1.0, float(row.ix_area or 0.0) / zone_area),
                    )
                )

            fault = await self._session.execute(
                text(
                    """
                    SELECT MIN(ST_Distance(sf.geom,
                        (SELECT geom FROM core.waterway_segment WHERE id = :segment_id)
                    )) AS dist
                    FROM core.structural_feature sf
                    WHERE sf.kind = 'FAULT'
                    """
                ),
                {"segment_id": str(segment_id)},
            )
            fault_dist = fault.scalar_one_or_none()

            confluence = await self._session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM core.waterway_segment other
                    WHERE other.id != :segment_id
                      AND ST_DWithin(
                            ST_EndPoint(other.geom),
                            (SELECT geom FROM core.waterway_segment WHERE id = :segment_id),
                            :radius)
                    """
                ),
                {"segment_id": str(segment_id), "radius": CONFLUENCE_RADIUS_M},
            )
            confluences = int(confluence.scalar_one() or 0)

            sinuosity = await self._session.execute(
                text(
                    """
                    SELECT CASE
                        WHEN ST_Distance(ST_StartPoint(geom), ST_EndPoint(geom)) > 0
                        THEN ST_Length(geom) /
                             ST_Distance(ST_StartPoint(geom), ST_EndPoint(geom))
                        ELSE NULL END AS s
                    FROM core.waterway_segment WHERE id = :segment_id
                    """
                ),
                {"segment_id": str(segment_id)},
            )
            sinuosity_value = sinuosity.scalar_one_or_none()

            wq = await self._session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM core.water_quality_point wq
                    WHERE wq.status IN ('ALERT', 'POLLUTED', 'BACTERIAL_RISK')
                      AND ST_DWithin(wq.geom,
                        (SELECT geom FROM core.waterway_segment WHERE id = :segment_id),
                        2000)
                    """
                ),
                {"segment_id": str(segment_id)},
            )
            wq_alerts = int(wq.scalar_one() or 0)

            return Ok(
                SegmentSpatialFacts(
                    upstream_lithologies=tuple(lithologies),
                    nearest_fault_distance=(
                        Meters(float(fault_dist)) if fault_dist is not None else None
                    ),
                    upstream_length_m=upstream_length,
                    confluence_count=confluences,
                    sinuosity=float(sinuosity_value) if sinuosity_value else None,
                    water_quality_alert_nearby=wq_alerts > 0,
                )
            )
        except SQLAlchemyError as exc:
            return Err(DatabaseError(code="SPATIAL_QUERY", message=str(exc)))

    async def midpoint_2039(
        self, segment_id: WaterwaySegmentId
    ) -> Result[tuple[float, float], DatabaseError]:
        try:
            result = await self._session.execute(
                text(
                    """
                    SELECT ST_X(p) AS x, ST_Y(p) AS y FROM (
                        SELECT ST_LineInterpolatePoint(geom, 0.5) AS p
                        FROM core.waterway_segment WHERE id = :segment_id
                    ) q
                    """
                ),
                {"segment_id": str(segment_id)},
            )
            row = result.one_or_none()
            if row is None:
                return Err(DatabaseError(code="NOT_FOUND", message=str(segment_id)))
            return Ok((float(row.x), float(row.y)))
        except SQLAlchemyError as exc:
            return Err(DatabaseError(code="SPATIAL_QUERY", message=str(exc)))
