import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HazardMap } from "./HazardMap";
import { fixtures, jsonResponse, stubFetch, type MockRoute } from "../test/mockApi";

// MapView pulls in Leaflet + satellite tiles; render a lightweight stub instead so
// these tests exercise the page wiring (filters, drawer, status updates).
vi.mock("../components/MapView", () => ({
  MapView: (props: {
    markers: Array<{ id: string; label: string; selected?: boolean }>;
    onMarkerClick?: (id: string) => void;
  }) => (
    <div data-testid="map-stub">
      {props.markers.map((m) => (
        <button
          key={m.id}
          data-testid={`marker-${m.id}`}
          aria-pressed={m.selected ? "true" : "false"}
          onClick={() => props.onMarkerClick?.(m.id)}
        >
          {m.label}
        </button>
      ))}
    </div>
  ),
}));

const H1 = fixtures.hazard("h1", -4.2749, 21.5426);
const H2 = fixtures.hazard("h2", -4.2742, 21.5432, {
  status: "new",
  report_count: 1,
  // Large bbox relative to its frame -> severe tier marker
  bbox_area_frac: 0.25,
});

function makeHandler(detailExtra: Record<string, unknown> = {}): MockRoute {
  return (url, method) => {
    if (method === "PATCH" && url === "/api/hazards/h1") {
      return jsonResponse(
        fixtures.hazardDetail("h1", H1.latitude, H1.longitude, {
          status: "resolved",
          resolved_at: "2026-11-19T11:00:00Z",
          resolved_note: "repaired by crew A",
          status_history: [
            {
              id: 7,
              previous_status: "confirmed",
              new_status: "resolved",
              note: "repaired by crew A",
              created_at: "2026-11-19T11:00:00Z",
            },
          ],
          ...detailExtra,
        }),
      );
    }
    if (url.startsWith("/api/hazards?")) {
      return jsonResponse({ items: [H1, H2], total: 2, page: 1, page_size: 200 });
    }
    if (url === "/api/hazards/h1") {
      return jsonResponse(fixtures.hazardDetail("h1", H1.latitude, H1.longitude));
    }
    if (url === "/api/hazards/h2") {
      return jsonResponse(fixtures.hazardDetail("h2", H2.latitude, H2.longitude));
    }
    return null;
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HazardMap (M6)", () => {
  it("renders matching hazards as markers with the local-demo banner", async () => {
    stubFetch(makeHandler());
    render(<HazardMap />);

    expect(await screen.findByTestId("marker-h1")).toBeInTheDocument();
    expect(screen.getByTestId("marker-h2")).toBeInTheDocument();
    expect(screen.getByText("LOCAL DEMO DATA")).toBeInTheDocument();
    expect(await screen.findByText("2 hazard(s) match")).toBeInTheDocument();
  });

  it("sizes each marker from the reported bbox area", async () => {
    stubFetch(makeHandler());
    render(<HazardMap />);

    // h1 has a small bbox/frame fraction, h2 a large one -> tier in the label
    expect((await screen.findByTestId("marker-h1")).textContent).toContain("small pothole");
    expect(screen.getByTestId("marker-h2").textContent).toContain("severe pothole");
  });

  it("sends filter changes to the hazard query", async () => {
    const calls = stubFetch(makeHandler());
    render(<HazardMap />);
    await screen.findByTestId("marker-h1");

    fireEvent.click(screen.getByRole("radio", { name: "resolved" }));
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes("status=resolved"))).toBe(true);
    });

    fireEvent.change(screen.getByLabelText("Min reports"), { target: { value: "3" } });
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes("min_reports=3"))).toBe(true);
    });
  });

  it("opens the detail drawer on marker click and supports resolve", async () => {
    const calls = stubFetch(makeHandler());
    render(<HazardMap />);
    await screen.findByTestId("marker-h1");

    fireEvent.click(screen.getByTestId("marker-h1"));

    expect(await screen.findByText("Hazard detail")).toBeInTheDocument();
    expect(await screen.findByText("×3")).toBeInTheDocument();
    // Drawer loaded the full detail (not just the list summary).
    expect(calls.some((c) => c.url === "/api/hazards/h1" && c.method === "GET")).toBe(true);
    expect(await screen.findByText("Observations (1)")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Note (optional)"), {
      target: { value: "repaired by crew A" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Mark resolved/ }));

    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH" && c.url === "/api/hazards/h1");
      expect(patch).toBeDefined();
      expect(patch!.body).toEqual({ status: "resolved", note: "repaired by crew A" });
    });

    // Drawer reflects the updated status, history entry and reopen control.
    expect(await screen.findByRole("button", { name: /Reopen/ })).toBeInTheDocument();
    expect(await screen.findByText("confirmed → resolved")).toBeInTheDocument();
    expect(document.querySelector(".nb-tag.bg-ink")).toBeInTheDocument();
  });
});
