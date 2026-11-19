import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MapView } from "./MapView";

const STORAGE_KEY = "roadwatch.base_layer";

const SATELLITE = { name: "Satellite imagery" };
const LABELLED = { name: "Satellite imagery with labels" };
const STREET = { name: "Street map" };

describe("MapView base-layer switcher (M6)", () => {
  afterEach(() => {
    window.localStorage.removeItem(STORAGE_KEY);
  });

  it("defaults to satellite view", () => {
    render(<MapView markers={[]} />);

    expect(screen.getByRole("button", SATELLITE)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", LABELLED)).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", STREET)).toHaveAttribute("aria-pressed", "false");
  });

  it("switches to the labelled satellite view and remembers the choice", () => {
    render(<MapView markers={[]} />);

    fireEvent.click(screen.getByRole("button", LABELLED));

    expect(screen.getByRole("button", LABELLED)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", SATELLITE)).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", STREET)).toHaveAttribute("aria-pressed", "false");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("satellite-labels");
  });

  it("switches to the street layer and remembers the choice", () => {
    render(<MapView markers={[]} />);

    fireEvent.click(screen.getByRole("button", STREET));

    expect(screen.getByRole("button", STREET)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", SATELLITE)).toHaveAttribute("aria-pressed", "false");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("street");
  });

  it("restores the saved layer on the next mount", () => {
    window.localStorage.setItem(STORAGE_KEY, "satellite-labels");

    render(<MapView markers={[]} />);

    expect(screen.getByRole("button", LABELLED)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", SATELLITE)).toHaveAttribute("aria-pressed", "false");
  });

  it("falls back to satellite when the saved value is not a known layer", () => {
    window.localStorage.setItem(STORAGE_KEY, "bogus");

    render(<MapView markers={[]} />);

    expect(screen.getByRole("button", SATELLITE)).toHaveAttribute("aria-pressed", "true");
  });
});

describe("MapView marker size tiers", () => {
  it("renders one icon box per tier, sized to match its CSS class", () => {
    render(
      <MapView
        markers={[
          { id: "a", lat: -4.27, lon: 21.54, label: "small", kind: "hazard-new", size: "small" },
          {
            id: "b",
            lat: -4.28,
            lon: 21.55,
            label: "severe",
            kind: "hazard-confirmed",
            size: "severe",
          },
          // No size -> medium fallback
          { id: "c", lat: -4.29, lon: 21.56, label: "default", kind: "hazard-new" },
        ]}
      />,
    );

    const bodies = document.querySelectorAll(".rw-marker__body");
    expect(bodies).toHaveLength(3);
    expect(bodies[0].className).toContain("rw-marker__body--size-small");
    expect(bodies[1].className).toContain("rw-marker__body--size-severe");
    expect(bodies[2].className).toContain("rw-marker__body--size-medium");

    // Leaflet sizes the icon box from iconSize, so the anchor stays centred.
    const icons = Array.from(
      document.querySelectorAll<HTMLElement>(".leaflet-marker-icon.rw-marker"),
    );
    expect(icons.map((el) => el.style.width)).toEqual(["16px", "30px", "22px"]);
    expect(icons.map((el) => el.style.marginLeft)).toEqual(["-8px", "-15px", "-11px"]);
  });
});
