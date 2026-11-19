import { describe, expect, it } from "vitest";
import { HAZARD_SIZE_PX, hazardSizeFor } from "./hazardSize";

describe("hazardSizeFor", () => {
  it("splits bbox/frame area into the three marker tiers", () => {
    expect(hazardSizeFor(0.004)).toBe("small"); // 0.4% of frame
    expect(hazardSizeFor(0.029)).toBe("small");
    expect(hazardSizeFor(0.03)).toBe("medium"); // boundary -> medium
    expect(hazardSizeFor(0.119)).toBe("medium");
    expect(hazardSizeFor(0.12)).toBe("severe"); // boundary -> severe
    expect(hazardSizeFor(0.45)).toBe("severe");
  });

  it("falls back to medium when the area is unknown", () => {
    expect(hazardSizeFor(null)).toBe("medium");
    expect(hazardSizeFor(undefined)).toBe("medium");
    expect(hazardSizeFor(Number.NaN)).toBe("medium");
    expect(hazardSizeFor(Number.POSITIVE_INFINITY)).toBe("medium");
  });

  it("keeps the three marker sizes strictly increasing", () => {
    expect(HAZARD_SIZE_PX.small).toBeLessThan(HAZARD_SIZE_PX.medium);
    expect(HAZARD_SIZE_PX.medium).toBeLessThan(HAZARD_SIZE_PX.severe);
  });
});
