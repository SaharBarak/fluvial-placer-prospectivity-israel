"""Copernicus Data Space STAC adapter (PRD §13.1 [R5]).

MVP scope: catalogue metadata evidence — Sentinel-2 L2A acquisition coverage
and cloud statistics over a bbox/time window. Raster download/processing is a
V1 concern; the system never claims Au detection from imagery (AC-14).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from goldflow.domain.results import Err, Ok, Result, StacError
from goldflow.infrastructure.http import FetchClient

SENTINEL2_L2A_COLLECTION = "sentinel-2-l2a"


@dataclass(frozen=True, slots=True)
class StacItemSummary:
    item_id: str
    datetime_iso: str
    cloud_cover_pct: float | None
    collection: str


class StacAdapter:
    def __init__(self, client: FetchClient, root: str) -> None:
        self._client = client
        self._root = root.rstrip("/")

    async def search_sentinel2(
        self,
        bbox_4326: tuple[float, float, float, float],
        date_from: str,
        date_to: str,
        limit: int = 50,
    ) -> Result[tuple[StacItemSummary, ...], StacError]:
        result = await self._client.get_json(
            f"{self._root}/search",
            {
                "collections": SENTINEL2_L2A_COLLECTION,
                "bbox": ",".join(str(v) for v in bbox_4326),
                "datetime": f"{date_from}T00:00:00Z/{date_to}T23:59:59Z",
                "limit": limit,
            },
        )
        match result:
            case Err(error):
                return Err(StacError(code=error.code, message=error.message))
            case Ok(payload):
                items: list[StacItemSummary] = []
                features = cast(
                    list[dict[str, Any]], cast(dict[str, Any], payload).get("features", [])
                )
                for feature in features:
                    props = cast(dict[str, Any], feature.get("properties") or {})
                    cloud = props.get("eo:cloud_cover")
                    items.append(
                        StacItemSummary(
                            item_id=str(feature.get("id")),
                            datetime_iso=str(props.get("datetime")),
                            cloud_cover_pct=float(cloud) if cloud is not None else None,
                            collection=str(feature.get("collection", SENTINEL2_L2A_COLLECTION)),
                        )
                    )
                return Ok(tuple(items))
        return Err(StacError(code="UNREACHABLE", message="match exhausted"))
