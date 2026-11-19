/** Local geometry helpers (mirror of backend/app/utils/geometry.py). */

const EARTH_RADIUS_M = 6_371_000;

/** Great-circle distance between two WGS84 points, in metres. */
export function haversineM(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const phi1 = toRad(lat1);
  const phi2 = toRad(lat2);
  const dphi = toRad(lat2 - lat1);
  const dlambda = toRad(lon2 - lon1);
  const a =
    Math.sin(dphi / 2) ** 2 +
    Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlambda / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a));
}

/** Initial bearing from point 1 to point 2, in degrees [0, 360). */
export function bearingDeg(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const phi1 = toRad(lat1);
  const phi2 = toRad(lat2);
  const dlambda = toRad(lon2 - lon1);
  const y = Math.sin(dlambda) * Math.cos(phi2);
  const x =
    Math.cos(phi1) * Math.sin(phi2) -
    Math.sin(phi1) * Math.cos(phi2) * Math.cos(dlambda);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

export interface RouteLeg {
  /** Cumulative distance from the route start to this vertex, in metres. */
  cumulative_m: number;
  lat: number;
  lon: number;
}

export interface VehiclePose {
  lat: number;
  lon: number;
  heading_deg: number;
}

/** Pre-compute cumulative distances for a route's vertices. */
export function buildLegs(points: Array<{ lat: number; lon: number }>): RouteLeg[] {
  const legs: RouteLeg[] = [];
  let cumulative = 0;
  for (let i = 0; i < points.length; i++) {
    if (i > 0) {
      cumulative += haversineM(
        points[i - 1].lat,
        points[i - 1].lon,
        points[i].lat,
        points[i].lon,
      );
    }
    legs.push({ cumulative_m: cumulative, lat: points[i].lat, lon: points[i].lon });
  }
  return legs;
}

/**
 * Vehicle pose at a given distance travelled along the route (metres from the
 * start). Clamps to the endpoints; the heading is the bearing of the current
 * segment (the last segment's bearing at the finish).
 */
export function poseAtDistance(legs: RouteLeg[], distance_m: number): VehiclePose | null {
  if (legs.length === 0) return null;
  const total = legs[legs.length - 1].cumulative_m;
  const d = Math.max(0, Math.min(distance_m, total));

  if (d <= 0) {
    const ahead = legs[1];
    if (!ahead) return { lat: legs[0].lat, lon: legs[0].lon, heading_deg: 0 };
    return {
      lat: legs[0].lat,
      lon: legs[0].lon,
      heading_deg: bearingDeg(legs[0].lat, legs[0].lon, ahead.lat, ahead.lon),
    };
  }

  // Find the segment containing d.
  let i = 1;
  while (i < legs.length - 1 && legs[i].cumulative_m < d) i++;
  const a = legs[i - 1];
  const b = legs[i];
  const segLen = b.cumulative_m - a.cumulative_m;
  const t = segLen > 0 ? (d - a.cumulative_m) / segLen : 0;
  return {
    lat: a.lat + (b.lat - a.lat) * t,
    lon: a.lon + (b.lon - a.lon) * t,
    heading_deg: bearingDeg(a.lat, a.lon, b.lat, b.lon),
  };
}
