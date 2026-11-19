/**
 * Map-marker size tiers derived from the YOLO bounding-box area.
 *
 * The backend reports the hazard's mean bbox area as a fraction of the source
 * frame (`bbox_area_frac`, see `summarize_bbox_areas`), which keeps hazards
 * recorded at different video resolutions comparable. Three simple tiers:
 *
 *   small   < 3% of the frame   (far / shallow pothole)
 *   medium   3% – 12%
 *   severe  ≥ 12%               (close / large pothole)
 *
 * A hazard without an area summary falls back to medium so the marker stays
 * visible regardless of data vintage.
 */
export type HazardSize = "small" | "medium" | "severe";

/** Marker box sizes in px — keep in sync with `.rw-marker__body--size-*`. */
export const HAZARD_SIZE_PX: Record<HazardSize, number> = {
  small: 16,
  medium: 22,
  severe: 30,
};

const MEDIUM_MIN_FRAC = 0.03;
const SEVERE_MIN_FRAC = 0.12;

/** Map a bbox/frame area fraction (0-1) to a marker size tier. */
export function hazardSizeFor(areaFrac: number | null | undefined): HazardSize {
  if (areaFrac == null || !Number.isFinite(areaFrac)) return "medium";
  if (areaFrac < MEDIUM_MIN_FRAC) return "small";
  if (areaFrac < SEVERE_MIN_FRAC) return "medium";
  return "severe";
}
