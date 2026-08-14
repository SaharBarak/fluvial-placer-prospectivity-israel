"""OSM Overpass adapter: waterway geometry carrier (SECONDARY authority).

Official flow classification comes from Water Authority datasets; OSM supplies
line geometry plus the ``intermittent`` tag as a weak seasonal prior. License:
ODbL — attribution required; stored in SourceRegistry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from goldflow.domain.results import Err, InfrastructureError, Ok, Result
from goldflow.infrastructure.http import FetchClient

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"


@dataclass(frozen=True, slots=True)
class OsmWaterway:
    way_id: int
    name: str | None
    waterway_class: str  # river | stream
    intermittent: bool
    coords_4326: tuple[tuple[float, float], ...]  # (lon, lat)


class OverpassAdapter:
    def __init__(self, client: FetchClient) -> None:
        self._client = client

    async def waterways(
        self, bbox_4326: tuple[float, float, float, float]
    ) -> Result[tuple[OsmWaterway, ...], InfrastructureError]:
        """Named rivers/streams intersecting bbox (south, west, north, east order
        for Overpass)."""
        min_lon, min_lat, max_lon, max_lat = bbox_4326
        query = (
            f'[out:json][timeout:90];way["waterway"~"^(river|stream)$"]'
            f"({min_lat},{min_lon},{max_lat},{max_lon});out geom;"
        )
        result = await self._client.post_json(OVERPASS_URL, data={"data": query})
        match result:
            case Err(error):
                return Err(error)
            case Ok(payload):
                data = cast(dict[str, Any], payload)
                ways: list[OsmWaterway] = []
                elements = cast(list[dict[str, Any]], data.get("elements", []))
                for element in elements:
                    if element.get("type") != "way":
                        continue
                    geometry = cast(list[dict[str, float]], element.get("geometry") or [])
                    if len(geometry) < 2:
                        continue
                    tags = cast(dict[str, str], element.get("tags") or {})
                    ways.append(
                        OsmWaterway(
                            way_id=int(element["id"]),
                            name=tags.get("name"),
                            waterway_class=str(tags.get("waterway", "stream")),
                            intermittent=tags.get("intermittent") == "yes",
                            coords_4326=tuple(
                                (float(p["lon"]), float(p["lat"])) for p in geometry
                            ),
                        )
                    )
                return Ok(tuple(ways))
        return Err(InfrastructureError(code="UNREACHABLE", message="match exhausted"))
