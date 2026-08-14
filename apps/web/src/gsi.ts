import type maplibregl from "maplibre-gl";

const GSI_VT_ROOT =
  "https://egozi.gsi.gov.il/arcgis/rest/services/Hosted/israel_formation_200000_tile/VectorTileServer";

interface EsriStyleLayer {
  id: string;
  type: string;
  source: string;
  "source-layer": string;
  filter?: unknown;
  minzoom?: number;
  maxzoom?: number;
  layout?: Record<string, unknown>;
  paint?: Record<string, unknown>;
}

interface EsriRootStyle {
  layers: EsriStyleLayer[];
}

/** Load the official GSI vector-tile style and graft its geology layers onto
 *  the live map as a semi-transparent overlay with source attribution. */
export async function addGsiGeologyOverlay(
  map: maplibregl.Map,
  opacity: number,
): Promise<string[]> {
  const response = await fetch(`${GSI_VT_ROOT}/resources/styles/root.json`);
  if (!response.ok) return [];
  const style = (await response.json()) as EsriRootStyle;

  map.addSource("gsi-geology", {
    type: "vector",
    tiles: [`${GSI_VT_ROOT}/tile/{z}/{y}/{x}.pbf`],
    minzoom: 0,
    maxzoom: 14,
    bounds: [34.2642, 29.5044, 35.9622, 33.3407],
    attribution:
      '<a href="https://www.gov.il/he/departments/geological-survey-of-israel">Geological Survey of Israel (GSI)</a>',
  });

  const added: string[] = [];
  for (const layer of style.layers) {
    if (layer.type !== "fill") continue; // polygons only; skip labels/lines
    const paint = { ...(layer.paint ?? {}) } as Record<string, unknown>;
    paint["fill-opacity"] = opacity;
    delete paint["fill-outline-color"];
    const id = `gsi-${layer.id}`;
    try {
      map.addLayer({
        id,
        type: "fill",
        source: "gsi-geology",
        "source-layer": layer["source-layer"],
        filter: layer.filter as never,
        minzoom: layer.minzoom ?? 0,
        maxzoom: 14,
        paint: paint as never,
      });
      added.push(id);
    } catch {
      // tolerate individual invalid layer defs; keep the rest
    }
  }
  return added;
}
