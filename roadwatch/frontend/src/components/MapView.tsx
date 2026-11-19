import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import { useEffect, useRef, useState } from "react";
import { HAZARD_SIZE_PX, type HazardSize } from "../utils/hazardSize";

/** A data point rendered on the map (hazard, waypoint, ...). */
export interface MapMarkerSpec {
  id: string;
  lat: number;
  lon: number;
  /** Hover tooltip text. */
  label: string;
  /** Drives the colour via the rw-marker__body--{kind} CSS class. */
  kind: string;
  /** Size tier derived from the YOLO bbox area; defaults to medium. */
  size?: HazardSize;
  selected?: boolean;
}

export interface VehicleSpec {
  lat: number;
  lon: number;
  heading_deg: number;
}

export interface MapViewProps {
  /** Data markers; memoize on the parent so playback ticks do not rebuild them. */
  markers: MapMarkerSpec[];
  selectedId?: string | null;
  onMarkerClick?: (id: string) => void;
  /** Simulated vehicle marker (updated in place, never re-clustered). */
  vehicle?: VehicleSpec | null;
  /** Warning-radius circle around a point (updated in place). */
  radiusCircle?: { lat: number; lon: number; radius_m: number } | null;
  /** Route polyline vertices (ordered along travel direction). */
  route?: Array<{ lat: number; lon: number }> | null;
  /** Cluster data markers instead of rendering them individually. */
  cluster?: boolean;
  /** Fit the map to markers/route whenever this key changes (filter or route id). */
  fitKey?: string;
  className?: string;
  ariaLabel?: string;
}

/** Switchable map base layer. Satellite is the default (see DEFAULT_BASE_LAYER). */
type BaseLayerKind = "satellite" | "satellite-labels" | "street";

interface BaseLayerSpec {
  /** Button label in the corner switcher. */
  label: string;
  /** Spoken name — clearer than the short button text. */
  ariaLabel: string;
  url: string;
  attribution: string;
  /**
   * Transparent layers stacked above the base tiles for as long as this layer
   * is active (place + road labels over the satellite imagery).
   */
  overlays?: string[];
}

const ESRI_ATTRIBUTION =
  'Tiles © <a href="https://www.esri.com/">Esri</a> — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community';
/** Fuller credit: the label overlays also draw on HERE, Garmin and OSM data. */
const ESRI_LABELLED_ATTRIBUTION =
  'Tiles © <a href="https://www.esri.com/">Esri</a>, Maxar, Earthstar, HERE, Garmin, © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

const ESRI_IMAGERY_URL =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const ESRI_REFERENCE_URL =
  "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/";

const BASE_LAYERS: Record<BaseLayerKind, BaseLayerSpec> = {
  satellite: {
    label: "Satellite",
    ariaLabel: "Satellite imagery",
    url: ESRI_IMAGERY_URL,
    attribution: ESRI_ATTRIBUTION,
  },
  "satellite-labels": {
    label: "Labels",
    ariaLabel: "Satellite imagery with labels",
    url: ESRI_IMAGERY_URL,
    attribution: ESRI_LABELLED_ATTRIBUTION,
    overlays: [
      ESRI_REFERENCE_URL + "World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
      ESRI_REFERENCE_URL + "World_Transportation/MapServer/tile/{z}/{y}/{x}",
    ],
  },
  street: {
    label: "Street",
    ariaLabel: "Street map",
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: OSM_ATTRIBUTION,
  },
};

/** localStorage key remembering the chosen base layer across refreshes. */
const BASE_LAYER_KEY = "roadwatch.base_layer";
const DEFAULT_BASE_LAYER: BaseLayerKind = "satellite";

/** Restore the saved base layer, falling back to satellite. */
function readStoredBaseLayer(): BaseLayerKind {
  try {
    const saved = window.localStorage.getItem(BASE_LAYER_KEY);
    return saved === "satellite" || saved === "satellite-labels" || saved === "street"
      ? saved
      : DEFAULT_BASE_LAYER;
  } catch {
    // Storage unavailable (private mode); satellite is the documented default.
    return DEFAULT_BASE_LAYER;
  }
}

/** Marker box size in px — matches the `.rw-marker__body--size-*` CSS. */
function markerPx(m: MapMarkerSpec): number {
  return HAZARD_SIZE_PX[m.size ?? "medium"];
}

function dataIcon(m: MapMarkerSpec): L.DivIcon {
  const px = markerPx(m);
  const size = m.size ?? "medium";
  return L.divIcon({
    html: `<div class="rw-marker__body rw-marker__body--${m.kind} rw-marker__body--size-${size}"></div>`,
    className: `rw-marker${m.selected ? " rw-marker--selected" : ""}`,
    iconSize: [px, px],
    iconAnchor: [px / 2, px / 2],
  });
}

function vehicleIcon(heading_deg: number): L.DivIcon {
  return L.divIcon({
    html: `<div class="rw-marker__body rw-marker__body--vehicle" style="transform:rotate(${heading_deg}deg)"></div>`,
    className: "rw-marker rw-marker--vehicle",
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

/**
 * Thin imperative wrapper around Leaflet (react-leaflet is not used, to keep
 * the dependency surface small). The map instance lives in a ref and is
 * removed on unmount, which also keeps React 19 StrictMode's double-invoke
 * of effects safe.
 */
export function MapView({
  markers,
  selectedId,
  onMarkerClick,
  vehicle,
  radiusCircle,
  route,
  cluster = false,
  fitKey,
  className = "",
  ariaLabel = "Interactive map",
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerLayerRef = useRef<L.LayerGroup | null>(null);
  const routeLayerRef = useRef<L.LayerGroup | null>(null);
  const vehicleRef = useRef<L.Marker | null>(null);
  const vehicleHeadingRef = useRef<number | null>(null);
  const circleRef = useRef<L.Circle | null>(null);
  // Base layers are built once with the map and swapped in place, so switching
  // style must not recreate the map (that would reset the viewport).
  const [baseLayer, setBaseLayer] = useState<BaseLayerKind>(readStoredBaseLayer);
  const baseLayerRef = useRef(baseLayer);
  baseLayerRef.current = baseLayer;
  // Each style owns a stack of tile layers (base + optional label overlays).
  const tileLayersRef = useRef<Partial<Record<BaseLayerKind, L.TileLayer[]>>>({});
  const activeTilesRef = useRef<L.TileLayer[]>([]);
  // Latest callback without rebuilding markers when its identity changes.
  const clickRef = useRef(onMarkerClick);
  clickRef.current = onMarkerClick;

  // --- Map lifecycle (create once, remove on unmount) -----------------------
  useEffect(() => {
    const el = containerRef.current;
    if (!el || mapRef.current) return;

    const map = L.map(el, {
      center: [-4.275, 21.5425],
      zoom: 15,
      zoomControl: true,
      attributionControl: true,
    });
    // Build every style's layer stack once; only the active stack is on the map.
    const tileLayers = Object.fromEntries(
      (Object.keys(BASE_LAYERS) as BaseLayerKind[]).map((kind) => {
        const spec = BASE_LAYERS[kind];
        const stack = [
          L.tileLayer(spec.url, { attribution: spec.attribution, maxZoom: 19 }),
          // Label overlays sit in the same pane but are added after the base,
          // so they paint on top of the imagery.
          ...(spec.overlays ?? []).map((url) =>
            L.tileLayer(url, { attribution: spec.attribution, maxZoom: 19 }),
          ),
        ];
        return [kind, stack] as const;
      }),
    ) as Record<BaseLayerKind, L.TileLayer[]>;
    tileLayersRef.current = tileLayers;
    const initialStack = tileLayers[baseLayerRef.current];
    initialStack.forEach((layer) => layer.addTo(map));
    activeTilesRef.current = initialStack;

    const routeLayer = L.layerGroup().addTo(map);
    const markerLayer: L.LayerGroup = cluster
      ? L.markerClusterGroup({
          showCoverageOnHover: false,
          maxClusterRadius: 45,
          iconCreateFunction: (c) =>
            L.divIcon({
              html: `<div>${c.getChildCount()}</div>`,
              className: "rw-cluster",
              iconSize: [40, 40],
            }),
        })
      : L.layerGroup();
    map.addLayer(markerLayer);

    mapRef.current = map;
    routeLayerRef.current = routeLayer;
    markerLayerRef.current = markerLayer;

    return () => {
      map.remove();
      mapRef.current = null;
      markerLayerRef.current = null;
      routeLayerRef.current = null;
      vehicleRef.current = null;
      vehicleHeadingRef.current = null;
      circleRef.current = null;
      tileLayersRef.current = {};
      activeTilesRef.current = [];
    };
  }, [cluster]);

  // --- Base-layer switch (satellite / labelled / street), kept across refreshes
  useEffect(() => {
    const map = mapRef.current;
    const next = tileLayersRef.current[baseLayer];
    if (!map || !next) return;
    if (activeTilesRef.current === next) return;
    for (const layer of activeTilesRef.current) map.removeLayer(layer);
    for (const layer of next) layer.addTo(map);
    activeTilesRef.current = next;
    try {
      window.localStorage.setItem(BASE_LAYER_KEY, baseLayer);
    } catch {
      // Storage unavailable; the choice simply will not persist.
    }
  }, [baseLayer]);

  // --- Route polyline --------------------------------------------------------
  useEffect(() => {
    const layer = routeLayerRef.current;
    if (!layer) return;
    layer.clearLayers();
    if (!route || route.length < 2) return;
    const latlngs = route.map((p) => [p.lat, p.lon] as L.LatLngExpression);
    // Neo-brutalist double stroke: fat accent under a hard black line.
    L.polyline(latlngs, { color: "#f5e642", weight: 9, lineCap: "square" }).addTo(layer);
    L.polyline(latlngs, { color: "#111111", weight: 3, lineCap: "square" }).addTo(layer);
  }, [route]);

  // --- Data markers -----------------------------------------------------------
  useEffect(() => {
    const layer = markerLayerRef.current;
    if (!layer) return;
    layer.clearLayers();
    for (const m of markers) {
      const marker = L.marker([m.lat, m.lon], {
        icon: dataIcon(m),
        title: m.label,
        keyboard: true,
        riseOnHover: true,
      });
      // Lift the tooltip clear of whatever size tier the marker is.
      marker.bindTooltip(m.label, {
        direction: "top",
        offset: [0, -(markerPx(m) / 2 + 2)],
      });
      marker.on("click", () => clickRef.current?.(m.id));
      layer.addLayer(marker);
    }
  }, [markers, selectedId]);

  // --- Simulated vehicle (updated in place each playback tick) ---------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (!vehicle) {
      if (vehicleRef.current) {
        map.removeLayer(vehicleRef.current);
        vehicleRef.current = null;
        vehicleHeadingRef.current = null;
      }
      return;
    }

    if (!vehicleRef.current) {
      const marker = L.marker([vehicle.lat, vehicle.lon], {
        icon: vehicleIcon(vehicle.heading_deg),
        zIndexOffset: 1000,
        keyboard: false,
      }).bindTooltip("Simulated vehicle", { direction: "top", offset: [0, -14] });
      marker.addTo(map);
      vehicleRef.current = marker;
      vehicleHeadingRef.current = vehicle.heading_deg;
      return;
    }

    vehicleRef.current.setLatLng([vehicle.lat, vehicle.lon]);
    // Re-render the chevron only when the heading actually changed.
    if (vehicleHeadingRef.current !== vehicle.heading_deg) {
      vehicleRef.current.setIcon(vehicleIcon(vehicle.heading_deg));
      vehicleHeadingRef.current = vehicle.heading_deg;
    }
  }, [vehicle]);

  // --- Warning-radius circle (updated in place) -------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (!radiusCircle || radiusCircle.radius_m <= 0) {
      if (circleRef.current) {
        map.removeLayer(circleRef.current);
        circleRef.current = null;
      }
      return;
    }

    if (circleRef.current) {
      circleRef.current.setLatLng([radiusCircle.lat, radiusCircle.lon]);
      circleRef.current.setRadius(radiusCircle.radius_m);
      return;
    }
    circleRef.current = L.circle([radiusCircle.lat, radiusCircle.lon], {
      radius: radiusCircle.radius_m,
      color: "#111111",
      weight: 2,
      dashArray: "6 6",
      fillColor: "#f5e642",
      fillOpacity: 0.15,
    }).addTo(map);
  }, [radiusCircle]);

  // --- Fit bounds whenever the dataset identity changes ------------------------
  const boundsKey =
    (fitKey ?? "") +
    "|" +
    markers.map((m) => `${m.id}:${m.lat},${m.lon}`).join(";") +
    (route?.length
      ? `|route:${route.length}:${route[0].lat},${route[0].lon}:${
          route[route.length - 1].lat
        },${route[route.length - 1].lon}`
      : "");

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    // Skip until the container has a real size (jsdom / hidden layouts);
    // fitting bounds in a zero-size viewport would corrupt the zoom level.
    const size = map.getSize();
    if (size.x <= 0 || size.y <= 0) return;
    const pts: L.LatLngExpression[] = [
      ...markers.map((m) => [m.lat, m.lon] as L.LatLngExpression),
      ...(route ?? []).map((p) => [p.lat, p.lon] as L.LatLngExpression),
    ];
    if (pts.length === 0) return;
    map.fitBounds(L.latLngBounds(pts), { padding: [48, 48], maxZoom: 17 });
    // Intentionally keyed on boundsKey only (see declaration above).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boundsKey]);

  return (
    <div
      className={`rw-map ${className}`}
      role="application"
      aria-label={ariaLabel}
    >
      <div ref={containerRef} className="rw-map__canvas" />
      <div className="rw-map__basemap" role="group" aria-label="Map style">
        {(Object.keys(BASE_LAYERS) as BaseLayerKind[]).map((kind) => (
          <button
            key={kind}
            type="button"
            className="rw-map__basemap-btn"
            aria-label={BASE_LAYERS[kind].ariaLabel}
            aria-pressed={baseLayer === kind}
            onClick={() => setBaseLayer(kind)}
          >
            {BASE_LAYERS[kind].label}
          </button>
        ))}
      </div>
    </div>
  );
}
