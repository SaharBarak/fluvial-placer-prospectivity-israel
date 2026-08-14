"""Water Authority / data.gov.il CKAN datastore adapter (PRD §6.1 [R2]).

Official hydrology: springs catalog + measured discharge, hydrometric
stations, streams registry (topology by name), water-quality sampling.
Coordinates arrive in EPSG:2039 (new Israel TM grid).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from goldflow.domain.results import Err, InfrastructureError, Ok, Result
from goldflow.infrastructure.http import FetchClient

SPRINGS_CATALOG_RESOURCE = "e0f10edd-2780-4221-97dc-3ac9d2f62cd0"
SPRING_DISCHARGE_RESOURCE = "26d650da-9d47-4dd5-8cbe-2f7d6955110b"
HYDRO_STATIONS_RESOURCE = "a0522b41-00ad-4367-a00a-2d97b050ec1d"
STREAMS_REGISTRY_RESOURCE = "b6b421ce-c8ad-4582-bdf2-765b5fb4fed5"
WATER_QUALITY_RESOURCE = "eea54e96-d51e-4def-b975-bd409eda7c64"


@dataclass(frozen=True, slots=True)
class SpringRecord:
    spring_id: int
    name: str
    name_en: str | None
    x_itm: float
    y_itm: float
    spring_type: str | None
    aquifer: str | None


@dataclass(frozen=True, slots=True)
class SpringDischargeRecord:
    spring_id: int
    hydro_year: str
    measured_on: str  # dd/mm/yyyy as published
    discharge_lps: float
    method: str | None


@dataclass(frozen=True, slots=True)
class HydroStationRecord:
    station_id: int
    name: str
    x_itm: float
    y_itm: float
    catchment_km2: float | None
    basin: str | None
    active: bool


@dataclass(frozen=True, slots=True)
class StreamRegistryRecord:
    stream_id: int
    name: str
    flows_into: str | None
    basin: str | None


class WaterAuthorityAdapter:
    def __init__(self, client: FetchClient, root: str) -> None:
        self._client = client
        self._root = root.rstrip("/")

    async def _datastore_all(
        self, resource_id: str, page_size: int = 1000, max_rows: int = 20000
    ) -> Result[tuple[dict[str, Any], ...], InfrastructureError]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while len(rows) < max_rows:
            result = await self._client.get_json(
                f"{self._root}/datastore_search",
                {"resource_id": resource_id, "limit": page_size, "offset": offset},
            )
            match result:
                case Err(error):
                    return Err(error)
                case Ok(payload):
                    data = cast(dict[str, Any], payload)
                    if not data.get("success"):
                        return Err(
                            InfrastructureError(
                                code="CKAN_ERROR", message=f"resource {resource_id}"
                            )
                        )
                    records = cast(
                        list[dict[str, Any]],
                        cast(dict[str, Any], data["result"]).get("records") or [],
                    )
                    rows.extend(records)
                    if len(records) < page_size:
                        return Ok(tuple(rows))
                    offset += page_size
        return Ok(tuple(rows))

    async def springs(self) -> Result[tuple[SpringRecord, ...], InfrastructureError]:
        result = await self._datastore_all(SPRINGS_CATALOG_RESOURCE)
        match result:
            case Err(error):
                return Err(error)
            case Ok(rows):
                springs: list[SpringRecord] = []
                for row in rows:
                    x = row.get("נביעה X .נ.צ")
                    y = row.get("נביעה Y .נ.צ")
                    sid = row.get("מספר זיהוי")
                    if not (isinstance(x, (int, float)) and isinstance(y, (int, float)) and sid):
                        continue
                    springs.append(
                        SpringRecord(
                            spring_id=int(sid),
                            name=str(row.get("שם מעיין") or ""),
                            name_en=row.get("שם מעיין באנגלית"),
                            x_itm=float(x),
                            y_itm=float(y),
                            spring_type=row.get("סוג מעיין"),
                            aquifer=row.get("שם אקויפר"),
                        )
                    )
                return Ok(tuple(springs))
        return Err(InfrastructureError(code="UNREACHABLE", message="match exhausted"))

    async def spring_discharges(
        self,
    ) -> Result[tuple[SpringDischargeRecord, ...], InfrastructureError]:
        result = await self._datastore_all(SPRING_DISCHARGE_RESOURCE, max_rows=50000)
        match result:
            case Err(error):
                return Err(error)
            case Ok(rows):
                discharges: list[SpringDischargeRecord] = []
                for row in rows:
                    sid = row.get("מספר זיהוי")
                    q = row.get("ספיקה (ליטר/שניה)")
                    when = row.get("תאריך מדידת ספיקה")
                    if sid is None or q is None or not when:
                        continue
                    try:
                        discharge = float(q)
                    except (TypeError, ValueError):
                        continue
                    discharges.append(
                        SpringDischargeRecord(
                            spring_id=int(sid),
                            hydro_year=str(row.get("שנה הידרולוגית") or ""),
                            measured_on=str(when),
                            discharge_lps=discharge,
                            method=row.get("שיטת מדידה"),
                        )
                    )
                return Ok(tuple(discharges))
        return Err(InfrastructureError(code="UNREACHABLE", message="match exhausted"))

    async def hydro_stations(
        self,
    ) -> Result[tuple[HydroStationRecord, ...], InfrastructureError]:
        result = await self._datastore_all(HYDRO_STATIONS_RESOURCE)
        match result:
            case Err(error):
                return Err(error)
            case Ok(rows):
                stations: list[HydroStationRecord] = []
                for row in rows:
                    x = row.get("נ.צ. X (רוחב)")
                    y = row.get("נ.צ. Y (רוחב)")
                    sid = row.get("זיהוי תחנה")
                    if not (isinstance(x, (int, float)) and isinstance(y, (int, float)) and sid):
                        continue
                    stations.append(
                        HydroStationRecord(
                            station_id=int(sid),
                            name=str(row.get("שם עברית") or ""),
                            x_itm=float(x),
                            y_itm=float(y),
                            catchment_km2=(
                                float(row["שטח היקוות (קמ''ר)"])
                                if isinstance(row.get("שטח היקוות (קמ''ר)"), (int, float))
                                else None
                            ),
                            basin=row.get("תחום התנקזות של נחל ראשי"),
                            active=str(row.get("סטטוס תחנה נוכחי") or "") == "פעילה",
                        )
                    )
                return Ok(tuple(stations))
        return Err(InfrastructureError(code="UNREACHABLE", message="match exhausted"))

    async def streams_registry(
        self,
    ) -> Result[tuple[StreamRegistryRecord, ...], InfrastructureError]:
        result = await self._datastore_all(STREAMS_REGISTRY_RESOURCE)
        match result:
            case Err(error):
                return Err(error)
            case Ok(rows):
                streams: list[StreamRegistryRecord] = []
                for row in rows:
                    sid = row.get("זיהוי נחל")
                    name = row.get("שם נחל")
                    if sid is None or not name:
                        continue
                    streams.append(
                        StreamRegistryRecord(
                            stream_id=int(sid),
                            name=str(name),
                            flows_into=row.get("נחל אליו הוא נשפך"),
                            basin=row.get("תחום התנקזות ראשי"),
                        )
                    )
                return Ok(tuple(streams))
        return Err(InfrastructureError(code="UNREACHABLE", message="match exhausted"))
