import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { addGsiGeologyOverlay } from "./gsi";
import { DossierPanel } from "./DossierPanel";
import type { Dossier, TargetProperties } from "./types";

const FLOW_COLORS: Record<string, string> = {
  VERIFIED_PERENNIAL: "#0d47a1",
  VERIFIED_CURRENT: "#1976d2",
  SEASONAL_EXPECTED: "#90caf9",
  EPHEMERAL: "#cfd8dc",
  DRY: "#b0bec5",
  UNKNOWN: "#e0e0e0",
};

export default function App() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const gsiLayerIds = useRef<string[]>([]);
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [gsiVisible, setGsiVisible] = useState(true);
  const [status, setStatus] = useState("טוען…");

  const loadDossier = useCallback(async (targetId: string) => {
    const response = await fetch(`/v1/targets/${targetId}/dossier`);
    if (response.ok) setDossier((await response.json()) as Dossier);
  }, []);

  const refreshTargets = useCallback(async () => {
    const map = mapRef.current;
    if (!map) return;
    const data = await fetch("/v1/targets").then((r) => r.json());
    const source = map.getSource("targets") as maplibregl.GeoJSONSource | undefined;
    if (source) source.setData(data);
  }, []);

  const submitAssay = useCallback(
    async (targetId: string, valuePpb: number) => {
      setStatus("שולח תוצאת מעבדה ומדרג מחדש…");
      const response = await fetch("/v1/assay-results", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `assay-${targetId}-${Date.now()}`,
        },
        body: JSON.stringify({
          target_id: targetId,
          analyte: "Au",
          value: valuePpb,
          unit: "ppb",
          lab: "demo-lab",
        }),
      });
      if (response.ok) {
        await refreshTargets();
        await loadDossier(targetId);
        setStatus("דורג מחדש לאחר תוצאת מעבדה");
      } else {
        setStatus(`שליחת התוצאה נכשלה: ${response.status}`);
      }
    },
    [refreshTargets, loadDossier],
  );

  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: mapContainer.current,
      center: [35.45, 33.05],
      zoom: 9.2,
      style: {
        version: 8,
        glyphs:
          "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors",
          },
        },
        layers: [
          {
            id: "osm",
            type: "raster",
            source: "osm",
            paint: { "raster-saturation": -0.6, "raster-opacity": 0.9 },
          },
        ],
      },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl(), "top-left");

    map.on("load", async () => {
      gsiLayerIds.current = await addGsiGeologyOverlay(map, 0.35);

      const segments = await fetch("/v1/geo/segments").then((r) => r.json());
      map.addSource("segments", { type: "geojson", data: segments });
      map.addLayer({
        id: "segments",
        type: "line",
        source: "segments",
        paint: {
          "line-color": [
            "match",
            ["get", "flow_status"],
            "VERIFIED_PERENNIAL",
            FLOW_COLORS.VERIFIED_PERENNIAL,
            "VERIFIED_CURRENT",
            FLOW_COLORS.VERIFIED_CURRENT,
            "SEASONAL_EXPECTED",
            FLOW_COLORS.SEASONAL_EXPECTED,
            "EPHEMERAL",
            FLOW_COLORS.EPHEMERAL,
            "DRY",
            FLOW_COLORS.DRY,
            "#e0e0e0",
          ],
          "line-width": [
            "match",
            ["get", "flow_status"],
            "VERIFIED_PERENNIAL",
            3,
            "VERIFIED_CURRENT",
            2.4,
            1.2,
          ],
        },
      });

      const springs = await fetch("/v1/geo/springs").then((r) => r.json());
      map.addSource("springs", { type: "geojson", data: springs });
      map.addLayer({
        id: "springs",
        type: "circle",
        source: "springs",
        paint: {
          "circle-radius": 3,
          "circle-color": "#00acc1",
          "circle-stroke-width": 1,
          "circle-stroke-color": "#ffffff",
        },
      });

      const targets = await fetch("/v1/targets").then((r) => r.json());
      map.addSource("targets", { type: "geojson", data: targets });
      map.addLayer({
        id: "targets",
        type: "circle",
        source: "targets",
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["coalesce", ["get", "score"], 0],
            0,
            5,
            100,
            13,
          ],
          "circle-color": [
            "interpolate",
            ["linear"],
            ["coalesce", ["get", "score"], 0],
            0,
            "#ffe082",
            50,
            "#ffb300",
            75,
            "#e65100",
          ],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#4e342e",
          "circle-opacity": 0.9,
        },
      });
      map.addLayer({
        id: "target-ranks",
        type: "symbol",
        source: "targets",
        layout: {
          "text-field": ["to-string", ["get", "rank"]],
          "text-size": 10,
          "text-font": ["Noto Sans Regular"],
        },
        paint: { "text-color": "#ffffff" },
      });

      map.on("click", "targets", (e) => {
        const feature = e.features?.[0];
        if (!feature) return;
        const props = feature.properties as unknown as TargetProperties;
        void loadDossier(props.id);
      });
      map.on("mouseenter", "targets", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "targets", () => {
        map.getCanvas().style.cursor = "";
      });

      setStatus(`${targets.features.length} מטרות · ${segments.features.length} מקטעים`);
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [loadDossier]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const id of gsiLayerIds.current) {
      if (map.getLayer(id))
        map.setLayoutProperty(id, "visibility", gsiVisible ? "visible" : "none");
    }
  }, [gsiVisible]);

  return (
    <div className="app">
      <div ref={mapContainer} className="map" />
      <div className="topbar">
        <h1>GoldFlow Israel</h1>
        <span className="status">{status}</span>
        <label className="toggle">
          <input
            type="checkbox"
            checked={gsiVisible}
            onChange={(e) => setGsiVisible(e.target.checked)}
          />
          שכבת גיאולוגיה GSI
        </label>
        <span className="legend">
          <i style={{ background: FLOW_COLORS.VERIFIED_PERENNIAL }} /> איתן
          <i style={{ background: FLOW_COLORS.VERIFIED_CURRENT }} /> זרימה מאומתת
          <i style={{ background: FLOW_COLORS.SEASONAL_EXPECTED }} /> עונתי
        </span>
      </div>
      {dossier && (
        <DossierPanel
          dossier={dossier}
          onClose={() => setDossier(null)}
          onSubmitAssay={submitAssay}
        />
      )}
    </div>
  );
}
