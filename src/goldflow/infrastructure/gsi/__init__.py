"""GSI ArcGIS adapter (PRD §4, §12.3).

Discovers service metadata instead of hardcoding layer URLs; queries feature
layers as GeoJSON pages; exposes an export-image URL template for the map
overlay with attribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from goldflow.domain.results import ArcGisError, Err, Ok, Result
from goldflow.infrastructure.http import FetchClient

GEOLOGY_SERVICE = "Hosted/Israel_200000_2014_geology"
ATTRIBUTION = "Geological Survey of Israel (GSI) — egozi.gsi.gov.il"


@dataclass(frozen=True, slots=True)
class GsiLayer:
    id: int
    name: str
    geometry_type: str


@dataclass(frozen=True, slots=True)
class GsiFeature:
    layer_id: int
    feature_ref: str
    properties: dict[str, Any]
    geometry: dict[str, Any]  # GeoJSON geometry, EPSG:4326


class GsiArcGisAdapter:
    def __init__(self, client: FetchClient, root: str) -> None:
        self._client = client
        self._root = root.rstrip("/")

    async def discover_layers(
        self, service: str = GEOLOGY_SERVICE
    ) -> Result[tuple[GsiLayer, ...], ArcGisError]:
        url = f"{self._root}/{service}/FeatureServer"
        result = await self._client.get_json(url, {"f": "json"})
        match result:
            case Ok(payload):
                layers = cast(
                    list[dict[str, Any]], cast(dict[str, Any], payload).get("layers") or []
                )
                return Ok(
                    tuple(
                        GsiLayer(
                            id=int(layer["id"]),
                            name=str(layer["name"]),
                            geometry_type=str(layer.get("geometryType", "")),
                        )
                        for layer in layers
                    )
                )
            case Err(error):
                return Err(ArcGisError(code=error.code, message=error.message, service=service))
        return Err(ArcGisError(code="UNREACHABLE", message="match exhausted", service=service))

    async def query_layer(
        self,
        layer_id: int,
        *,
        service: str = GEOLOGY_SERVICE,
        bbox_4326: tuple[float, float, float, float] | None = None,
        max_features: int = 4000,
    ) -> Result[tuple[GsiFeature, ...], ArcGisError]:
        """Paged GeoJSON query with envelope filter."""
        url = f"{self._root}/{service}/FeatureServer/{layer_id}/query"
        features: list[GsiFeature] = []
        offset = 0
        page_size = 1000
        while len(features) < max_features:
            params: dict[str, Any] = {
                "where": "1=1",
                "outFields": "*",
                "f": "geojson",
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "outSR": 4326,
            }
            if bbox_4326 is not None:
                min_lon, min_lat, max_lon, max_lat = bbox_4326
                params.update(
                    {
                        "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
                        "geometryType": "esriGeometryEnvelope",
                        "inSR": 4326,
                        "spatialRel": "esriSpatialRelIntersects",
                    }
                )
            page = await self._client.get_json(url, params)
            match page:
                case Err(error):
                    return Err(
                        ArcGisError(code=error.code, message=error.message, service=service)
                    )
                case Ok(payload):
                    got = cast(
                        list[dict[str, Any]],
                        cast(dict[str, Any], payload).get("features") or [],
                    )
                    for raw in got:
                        props = cast(dict[str, Any], raw.get("properties") or {})
                        geometry = cast(dict[str, Any] | None, raw.get("geometry"))
                        if geometry is None:
                            continue
                        ref = str(
                            props.get("globalid") or props.get("fid") or props.get("OBJECTID")
                        )
                        features.append(
                            GsiFeature(
                                layer_id=layer_id,
                                feature_ref=ref,
                                properties=props,
                                geometry=geometry,
                            )
                        )
                    if len(got) < page_size:
                        return Ok(tuple(features))
                    offset += page_size
        return Ok(tuple(features))

    def export_image_url_template(self, service: str = GEOLOGY_SERVICE) -> str:
        """MapLibre raster source tiles template via ArcGIS export (FeatureServer
        services render through the companion MapServer path when available)."""
        return (
            f"{self._root}/{service}/MapServer/export"
            "?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857&size=256,256"
            "&format=png32&transparent=true&f=image"
        )
