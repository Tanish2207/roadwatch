import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import { useEffect, useRef } from "react";

/** A data point rendered on the map (hazard, waypoint, ...). */
export interface MapMarkerSpec {
  id: string;
  lat: number;
  lon: number;
  /** Hover tooltip text. */
  label: string;
  /** Drives the colour via the rw-marker__body--{kind} CSS class. */
  kind: string;
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

const OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function dataIcon(m: MapMarkerSpec): L.DivIcon {
  return L.divIcon({
    html: `<div class="rw-marker__body rw-marker__body--${m.kind}"></div>`,
    className: `rw-marker${m.selected ? " rw-marker--selected" : ""}`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
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
    L.tileLayer(OSM_URL, { attribution: OSM_ATTRIBUTION, maxZoom: 19 }).addTo(map);

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
    };
  }, [cluster]);

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
      marker.bindTooltip(m.label, { direction: "top", offset: [0, -13] });
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
      ref={containerRef}
      className={`rw-map ${className}`}
      role="application"
      aria-label={ariaLabel}
    />
  );
}
