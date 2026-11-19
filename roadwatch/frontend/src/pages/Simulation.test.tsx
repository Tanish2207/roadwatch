import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Simulation } from "./Simulation";
import { fixtures, jsonResponse, stubFetch } from "../test/mockApi";

// MapView pulls in Leaflet + OSM tiles; the stub exposes route/vehicle state
// so these tests can focus on playback control and the alert feed (§18.3).
vi.mock("../components/MapView", () => ({
  MapView: (props: {
    markers: Array<{ id: string }>;
    vehicle?: { lat: number; lon: number; heading_deg: number } | null;
    route?: Array<{ lat: number; lon: number }> | null;
    radiusCircle?: { radius_m: number } | null;
  }) => (
    <div data-testid="map-stub">
      <span data-testid="marker-count">{props.markers.length}</span>
      {props.vehicle ? (
        <span data-testid="vehicle">{props.vehicle.heading_deg.toFixed(0)}</span>
      ) : null}
      {props.route ? <span data-testid="route">{props.route.length}</span> : null}
      {props.radiusCircle ? (
        <span data-testid="radius">{props.radiusCircle.radius_m}</span>
      ) : null}
    </div>
  ),
}));

const ALERT = {
  hazard_id: "h1",
  latitude: -4.2747,
  longitude: 21.5429,
  status: "confirmed",
  report_count: 3,
  confidence_avg: 0.62,
  distance_m: 42.3,
  bearing_deg: 38,
  corridor_filtered: true,
};

const CORRIDOR_NOTE = "Approximate forward corridor (heading-angle filter).";

function makeHandler() {
  let alertCalls = 0;
  return (url: string, _method: string): Response | null => {
    switch (true) {
      case url === "/api/simulation/routes":
        return jsonResponse({
          items: [
            {
              id: "potholed-road",
              name: "Potholed Road (synthetic)",
              description: "Synthetic 26 s track.",
              is_synthetic: true,
              distance_m: 200,
              point_count: 11,
            },
          ],
        });
      case url.startsWith("/api/simulation/routes/"):
        return jsonResponse(fixtures.routeDetail());
      case url.startsWith("/api/hazards?"):
        return jsonResponse({
          items: [fixtures.hazard("h1", -4.2747, 21.5429)],
          total: 1,
          page: 1,
          page_size: 200,
        });
      case url === "/api/settings":
        return jsonResponse({ defaults: { sim_corridor_angle_deg: 60 } });
      case url === "/api/simulation/start":
        return jsonResponse({
          running: true,
          route_id: "potholed-road",
          speed_mps: 8,
          warning_distance_m: 150,
          elapsed_seconds: 0,
          alerted_hazard_ids: [],
        });
      case url === "/api/simulation/stop":
        return jsonResponse({
          running: false,
          route_id: null,
          speed_mps: 10,
          warning_distance_m: 150,
          elapsed_seconds: 0,
          alerted_hazard_ids: [],
        });
      case url === "/api/simulation/alerts":
        alertCalls += 1;
        // First tick: one eligible hazard; later ticks: server-side dedup.
        return jsonResponse({
          alerts: alertCalls === 1 ? [ALERT] : [],
          alerted_hazard_ids: ["h1"],
          vehicle_heading_deg: 45,
          corridor_applied: true,
          corridor_note: CORRIDOR_NOTE,
        });
      default:
        return null;
    }
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function startPlayback(calls: { method: string; url: string }[]) {
  render(<Simulation />);
  // Route auto-selects, detail loads, vehicle appears.
  expect(await screen.findByTestId("vehicle")).toBeInTheDocument();
  expect(screen.getByTestId("route")).toBeInTheDocument();
  expect(screen.getByTestId("radius")).toHaveTextContent("150");

  const play = screen.getByRole("button", { name: "Play" });
  await waitFor(() => expect(play).toBeEnabled());
  fireEvent.click(play);
  return { play, calls };
}

describe("Simulation (M7)", () => {
  it("draws the demo route and drives the simulated vehicle on play", async () => {
    const calls = stubFetch(makeHandler());
    const { play } = await startPlayback(calls);

    // Vehicle starts moving (simulated) and the map keeps hazards in view.
    expect(await screen.findByText(/VEHICLE MOVING \(SIMULATED\)/)).toBeInTheDocument();
    await waitFor(() => {
      expect(calls.filter((c) => c.url === "/api/simulation/start")).toHaveLength(1);
      expect(calls.some((c) => c.url === "/api/simulation/alerts")).toBe(true);
    });
    expect(play).toBeDisabled();
    await waitFor(() => expect(screen.getByTestId("marker-count")).toHaveTextContent("1"));
  });

  it("shows a non-repeating alert with corridor labelling", async () => {
    const calls = stubFetch(makeHandler());
    await startPlayback(calls);

    // Alert from the first query lands in the feed.
    expect(await screen.findByText("1 alert this session")).toBeInTheDocument();
    expect(await screen.findByText("42 m")).toBeInTheDocument();
    expect(screen.getByText("CORRIDOR ✓ (APPROX)")).toBeInTheDocument();
    expect(screen.getByText(/Approximate forward corridor/)).toBeInTheDocument();
    expect(screen.getByText("NO REPEATS — DEDUPED PER RUN")).toBeInTheDocument();

    // Keep playing past several query ticks: dedup keeps the feed at one.
    await new Promise((r) => setTimeout(r, 900));
    expect(screen.getByText("1 alert this session")).toBeInTheDocument();
    expect(calls.filter((c) => c.url === "/api/simulation/alerts").length).toBeGreaterThan(1);
  });

  it("pause keeps the session and reset stops it and clears the feed", async () => {
    const calls = stubFetch(makeHandler());
    const { play } = await startPlayback(calls);
    await screen.findByText("1 alert this session");

    // Pause: no new session start, playback stops.
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(play).toBeEnabled());
    expect(calls.filter((c) => c.url === "/api/simulation/start")).toHaveLength(1);

    // Resume keeps the same session (dedup survives pause).
    fireEvent.click(play);
    await waitFor(() => expect(play).toBeDisabled());

    // Reset stops the session server-side and clears the feed.
    fireEvent.click(screen.getByRole("button", { name: "Stop and reset" }));
    expect(await screen.findByText("No alerts yet")).toBeInTheDocument();
    await waitFor(() => {
      expect(calls.filter((c) => c.url === "/api/simulation/stop").length).toBeGreaterThan(0);
    });
  });
});
