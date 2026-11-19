/** Shared API response types (mirrors backend Pydantic schemas). */

export interface ModelStatus {
  ready: boolean;
  filename: string | null;
  source: string | null;
  classes: string[] | null;
  hint: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  backend: string;
  database: string;
  model: ModelStatus;
  environment: string;
  time: string;
}

export interface SettingsResponse {
  app: { name: string; environment: string };
  model: ModelStatus;
  defaults: {
    sample_rate_fps: number;
    confidence_threshold: number;
    image_size: number;
    gps_max_tolerance_seconds: number;
    aggregation_radius_m: number;
    sim_corridor_angle_deg: number;
  };
  limits: {
    max_upload_mb: number;
    allowed_video_extensions: string[];
    allowed_gps_extensions: string[];
  };
  storage: { uploads_dir: string; processed_dir: string };
  privacy: { local_inference: boolean; statement: string; tile_provider: string };
}

export interface DetectionOut {
  id: number;
  frame_timestamp_seconds: number;
  class_name: string;
  class_id: number;
  confidence: number;
  bbox_xyxy: number[];
  gps_lat: number | null;
  gps_lon: number | null;
  gps_match_method: string;
  gps_match_delta_seconds: number | null;
  vehicle_heading: number | null;
  vehicle_speed: number | null;
  tracking_id: number | null;
}

/** One persisted YOLO-annotated frame (split comparison viewer). */
export interface FrameEntry {
  ordinal: number;
  frame_index: number;
  timestamp_s: number;
  detections: number;
  image_url: string;
}

export interface FrameManifest {
  items: FrameEntry[];
  total: number;
  sample_rate_fps: number;
  video_fps: number;
}

export type JobStatus =
  | "queued"
  | "processing"
  | "aggregating"
  | "completed"
  | "failed"
  | "cancelled";

export interface JobSummary {
  id: string;
  original_filename: string;
  status: JobStatus;
  progress_percent: number;
  frames_processed: number;
  detections_count: number;
  is_published: boolean;
  processing_config: Record<string, unknown>;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type HazardStatus = "new" | "observed" | "confirmed" | "resolved";

export interface HazardSummary {
  id: string;
  latitude: number;
  longitude: number;
  status: HazardStatus;
  report_count: number;
  confidence_avg: number | null;
  confidence_max: number | null;
  first_seen_at: string;
  last_seen_at: string;
  location_uncertainty_m: number | null;
  is_stale: boolean;
  /** Raw YOLO bbox aggregates (pixel counts + frame-normalized fractions). */
  pixel_area_summary: Record<string, unknown> | null;
  /** Mean bbox area as a fraction of the source frame — drives marker size. */
  bbox_area_frac: number | null;
}

export interface HazardObservationOut {
  id: number;
  job_id: string;
  frame_timestamp_seconds: number;
  class_name: string;
  confidence: number;
  gps_lat: number | null;
  gps_lon: number | null;
  created_at: string;
}

export interface StatusHistoryOut {
  id: number;
  previous_status: string | null;
  new_status: string;
  note: string | null;
  created_at: string;
}

/** Full hazard payload returned by GET /api/hazards/{id}. */
export interface HazardDetail extends HazardSummary {
  resolved_at: string | null;
  resolved_note: string | null;
  physical_area_m2: number | null;
  observations: HazardObservationOut[];
  observations_total: number;
  status_history: StatusHistoryOut[];
}

export interface RouteSummary {
  id: string;
  name: string;
  description: string;
  is_synthetic: boolean;
  distance_m: number;
  point_count: number;
}

export interface RoutePoint {
  lat: number;
  lon: number;
  timestamp_seconds: number;
}

/** Full route returned by GET /api/simulation/routes/{id}. */
export interface RouteDetail extends RouteSummary {
  points: RoutePoint[];
}

/** One playback tick: where the simulated vehicle is right now. */
export interface SimulationAlertRequest {
  route_id: string;
  latitude: number;
  longitude: number;
  heading_deg?: number | null;
  warning_distance_m: number;
}

export interface SimulationAlert {
  hazard_id: string;
  latitude: number;
  longitude: number;
  status: HazardStatus;
  report_count: number;
  confidence_avg: number | null;
  distance_m: number;
  bearing_deg: number;
  corridor_filtered: boolean;
}

export interface SimulationAlertResponse {
  alerts: SimulationAlert[];
  alerted_hazard_ids: string[];
  vehicle_heading_deg: number | null;
  corridor_applied: boolean;
  corridor_note: string;
}

export interface SimulationState {
  running: boolean;
  route_id: string | null;
  speed_mps: number;
  warning_distance_m: number;
  elapsed_seconds: number;
  alerted_hazard_ids: string[];
}
