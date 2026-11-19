import { describe, expect, it } from "vitest";
import { bearingDeg, buildLegs, haversineM, poseAtDistance } from "./geo";

describe("haversineM", () => {
  it("matches a known latitude arc", () => {
    // 0.001° of latitude ≈ 111.19 m on a spherical earth.
    expect(haversineM(0, 0, 0.001, 0)).toBeCloseTo(111.19, 1);
  });

  it("is zero for identical points and symmetric otherwise", () => {
    expect(haversineM(10, 20, 10, 20)).toBe(0);
    expect(haversineM(1, 2, 3, 4)).toBeCloseTo(haversineM(3, 4, 1, 2), 9);
  });
});

describe("bearingDeg", () => {
  it("points north and east", () => {
    expect(bearingDeg(0, 0, 1, 0)).toBeCloseTo(0, 1);
    expect(bearingDeg(0, 0, 0, 1)).toBeCloseTo(90, 1);
    expect(bearingDeg(0, 0, -1, 0)).toBeCloseTo(180, 1);
  });
});

describe("buildLegs + poseAtDistance", () => {
  const points = [
    { lat: 0, lon: 0 },
    { lat: 0.001, lon: 0 }, // ~111.19 m north
    { lat: 0.002, lon: 0 },
  ];
  const legs = buildLegs(points);

  it("accumulates distance from the start", () => {
    expect(legs[0].cumulative_m).toBe(0);
    expect(legs[1].cumulative_m).toBeCloseTo(111.19, 1);
    expect(legs[2].cumulative_m).toBeCloseTo(222.39, 1);
  });

  it("interpolates halfway along the first segment with the segment heading", () => {
    const p = poseAtDistance(legs, 55.6);
    expect(p).not.toBeNull();
    expect(p!.lat).toBeCloseTo(0.0005, 6);
    expect(p!.lon).toBeCloseTo(0, 6);
    expect(p!.heading_deg).toBeCloseTo(0, 1);
  });

  it("clamps to the start and end of the route", () => {
    const start = poseAtDistance(legs, -50)!;
    expect(start.lat).toBe(0);

    const end = poseAtDistance(legs, 999_999)!;
    expect(end.lat).toBeCloseTo(0.002, 6);
    expect(end.heading_deg).toBeCloseTo(0, 1);
  });

  it("handles empty routes", () => {
    expect(buildLegs([])).toEqual([]);
    expect(poseAtDistance([], 10)).toBeNull();
  });
});
