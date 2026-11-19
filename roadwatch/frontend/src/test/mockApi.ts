/** Shared fetch-mocking helpers for frontend component tests. */

interface MockCall {
  url: string;
  method: string;
  body: unknown;
}

export type MockRoute = (url: string, method: string, body: unknown) => Response | null;

/** Duck-typed Response — the API client only reads ok/status/statusText/json. */
export function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: async () => body,
  } as unknown as Response;
}

/**
 * Install a global fetch stub that routes to `handler`; returns the recorded
 * call list for assertions. Call `vi.unstubAllGlobals()` in afterEach.
 */
export function stubFetch(handler: MockRoute): MockCall[] {
  const calls: MockCall[] = [];
  const fetchMock = async (input: unknown, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown;
    if (typeof init?.body === "string") {
      try {
        body = JSON.parse(init.body);
      } catch {
        body = init.body;
      }
    }
    calls.push({ url, method, body });

    const res = handler(url, method, body);
    if (!res) throw new Error(`Unhandled fetch in test: ${method} ${url}`);
    return res;
  };
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

/** Common data factories so tests stay readable. */
export const fixtures = {
  hazard(id: string, lat: number, lon: number, extra: Record<string, unknown> = {}) {
    return {
      id,
      latitude: lat,
      longitude: lon,
      status: "confirmed",
      report_count: 3,
      confidence_avg: 0.62,
      confidence_max: 0.71,
      first_seen_at: "2026-11-19T10:00:00Z",
      last_seen_at: "2026-11-19T10:30:00Z",
      location_uncertainty_m: 9.4,
      is_stale: false,
      pixel_area_summary: {
        count: 3,
        mean_area_px: 18400,
        max_area_px: 24600,
        frac_count: 3,
        mean_area_frac: 0.012,
        max_area_frac: 0.016,
      },
      bbox_area_frac: 0.012,
      ...extra,
    };
  },

  hazardDetail(id: string, lat: number, lon: number, extra: Record<string, unknown> = {}) {
    return {
      ...fixtures.hazard(id, lat, lon),
      resolved_at: null,
      resolved_note: null,
      physical_area_m2: null,
      observations: [
        {
          id: 1,
          job_id: "job-abc-123",
          frame_timestamp_seconds: 12.5,
          class_name: "pothole",
          confidence: 0.66,
          gps_lat: lat,
          gps_lon: lon,
          created_at: "2026-11-19T10:05:00Z",
        },
      ],
      observations_total: 1,
      status_history: [],
      ...extra,
    };
  },

  /** Demo route: 200 m straight-ish leg near the seeded hazards. */
  routeDetail(id = "potholed-road") {
    const points = Array.from({ length: 11 }, (_, i) => ({
      lat: -4.275002 + i * 0.0004,
      lon: 21.542498 + i * 0.0005,
      timestamp_seconds: i * 3,
    }));
    return {
      id,
      name: "Potholed Road (synthetic)",
      description: "Synthetic 26 s track.",
      is_synthetic: true,
      distance_m: 200,
      point_count: points.length,
      points,
    };
  },
};
