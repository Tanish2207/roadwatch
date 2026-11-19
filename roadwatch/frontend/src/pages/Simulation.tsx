import { MapPin, Pause, Play, RotateCcw, Square, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { MapView, type MapMarkerSpec } from "../components/MapView";
import { usePoll } from "../hooks/usePoll";
import type {
  HazardStatus,
  HazardSummary,
  Paginated,
  RouteDetail,
  RouteSummary,
  SettingsResponse,
  SimulationAlert,
  SimulationAlertResponse,
  SimulationState,
} from "../types/api";
import { buildLegs, poseAtDistance, type RouteLeg, type VehiclePose } from "../utils/geo";

const TICK_MS = 100;
const ALERT_QUERY_EVERY_TICKS = 3; // ~330 ms between alert queries
const STATUS_BG: Record<HazardStatus, string> = {
  new: "bg-accent-yellow",
  observed: "bg-accent-blue",
  confirmed: "bg-accent-coral",
  resolved: "bg-ink text-canvas",
};

interface FeedItem extends SimulationAlert {
  at: string;
}

/** Simulation — route playback against known hazards with per-session alerts (M7). */
export function Simulation() {
  const routes = usePoll<{ items: RouteSummary[] }>("/simulation/routes", 15000);
  const settings = usePoll<SettingsResponse>("/settings", 30000);
  const hazards = usePoll<Paginated<HazardSummary>>("/hazards?page=1&page_size=200", 15000);

  const [routeId, setRouteId] = useState("");
  const [routeDetail, setRouteDetail] = useState<RouteDetail | null>(null);
  const [speed, setSpeed] = useState(8);
  const [warning, setWarning] = useState(150);
  const [playing, setPlaying] = useState(false);
  const [finished, setFinished] = useState(false);
  const [busy, setBusy] = useState(false);
  const [distance, setDistance] = useState(0);
  const [pose, setPose] = useState<VehiclePose | null>(null);
  const [alerts, setAlerts] = useState<FeedItem[]>([]);
  const [corridorNote, setCorridorNote] = useState<string | null>(null);
  const [activeHazardId, setActiveHazardId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Refs so the playback interval reads the latest values without restarting.
  const legsRef = useRef<RouteLeg[]>([]);
  const speedRef = useRef(speed);
  const warningRef = useRef(warning);
  const routeIdRef = useRef(routeId);
  const distanceRef = useRef(0);
  const sessionRef = useRef(false); // server-side simulation session active

  useEffect(() => {
    speedRef.current = speed;
  }, [speed]);
  useEffect(() => {
    warningRef.current = warning;
  }, [warning]);
  useEffect(() => {
    routeIdRef.current = routeId;
  }, [routeId]);

  const routeItems = routes.data?.items ?? [];
  const selected = routeItems.find((r) => r.id === routeId) ?? null;

  // Auto-select the first demo route once the list arrives.
  useEffect(() => {
    if (!routeId && routeItems.length > 0) setRouteId(routeItems[0].id);
  }, [routeId, routeItems]);

  // --- Route detail ----------------------------------------------------------
  useEffect(() => {
    if (!routeId) {
      setRouteDetail(null);
      legsRef.current = [];
      return;
    }
    let cancelled = false;
    api
      .get<RouteDetail>(`/simulation/routes/${routeId}`)
      .then((d) => {
        if (cancelled) return;
        setRouteDetail(d);
        const legs = buildLegs(d.points);
        legsRef.current = legs;
        distanceRef.current = 0;
        setDistance(0);
        setFinished(false);
        const start = poseAtDistance(legs, 0);
        setPose(start);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Failed to load route");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [routeId]);

  const totalDistance = useMemo(() => {
    if (!routeDetail) return 0;
    const legs = buildLegs(routeDetail.points);
    return legs.length > 0 ? legs[legs.length - 1].cumulative_m : 0;
  }, [routeDetail]);

  const routePoints = useMemo(
    () => routeDetail?.points.map((p) => ({ lat: p.lat, lon: p.lon })) ?? null,
    [routeDetail],
  );

  // --- Alert queries (server-side logic + per-session dedup) ------------------
  const queryAlerts = useCallback(async (p: VehiclePose) => {
    try {
      const res = await api.post<SimulationAlertResponse>("/simulation/alerts", {
        route_id: routeIdRef.current,
        latitude: p.lat,
        longitude: p.lon,
        heading_deg: p.heading_deg,
        warning_distance_m: warningRef.current,
      });
      setCorridorNote(res.corridor_note);
      if (res.alerts.length > 0) {
        const stamped = res.alerts.map((a) => ({
          ...a,
          at: new Date().toLocaleTimeString(),
        }));
        setAlerts((prev) => [...stamped, ...prev].slice(0, 50));
        setActiveHazardId(res.alerts[0].hazard_id);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Server session lost (e.g. backend restarted) — re-arm it once.
        sessionRef.current = false;
        try {
          await api.post<SimulationState>("/simulation/start", {
            route_id: routeIdRef.current,
            speed_mps: speedRef.current,
            warning_distance_m: warningRef.current,
          });
          sessionRef.current = true;
        } catch {
          /* next tick will retry; errors surface if persistent */
        }
      } else if (err instanceof ApiError && err.status !== 0) {
        setError(err.message);
      }
    }
  }, []);

  // --- Playback loop ----------------------------------------------------------
  useEffect(() => {
    if (!playing) return;
    const legs = legsRef.current;
    if (legs.length < 2) return;
    const total = legs[legs.length - 1].cumulative_m;
    let tick = 0;

    const id = window.setInterval(() => {
      tick += 1;
      let d = distanceRef.current + speedRef.current * (TICK_MS / 1000);
      let done = false;
      if (d >= total) {
        d = total;
        done = true;
      }
      distanceRef.current = d;
      setDistance(d);

      const p = poseAtDistance(legs, d);
      if (p) setPose(p);

      // Alert queries are throttled; dedup happens server-side per session.
      if (p && tick % ALERT_QUERY_EVERY_TICKS === 0) void queryAlerts(p);
      if (done) {
        setPlaying(false);
        setFinished(true);
      }
    }, TICK_MS);

    return () => window.clearInterval(id);
  }, [playing, queryAlerts]);

  // --- Session control ---------------------------------------------------------
  const startSession = async () => {
    await api.post<SimulationState>("/simulation/start", {
      route_id: routeIdRef.current,
      speed_mps: speedRef.current,
      warning_distance_m: warningRef.current,
    });
    sessionRef.current = true;
  };

  const stopSession = async () => {
    try {
      await api.post<SimulationState>("/simulation/stop");
    } catch {
      /* already stopped */
    }
    sessionRef.current = false;
  };

  const play = async () => {
    if (!routeDetail || legsRef.current.length < 2 || busy) return;
    setError(null);
    setBusy(true);
    try {
      if (finished) {
        // Replay from the top starts a NEW session (dedup set resets).
        await stopSession();
        await startSession();
        distanceRef.current = 0;
        setDistance(0);
        setAlerts([]);
        setActiveHazardId(null);
        setFinished(false);
        setPose(poseAtDistance(legsRef.current, 0));
      } else if (!sessionRef.current) {
        await startSession();
      }
      setPlaying(true);
      // Query once immediately: hazards near the route start may already be
      // inside the warning radius on the first frame.
      const p = poseAtDistance(legsRef.current, distanceRef.current);
      if (p) void queryAlerts(p);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the simulation");
    } finally {
      setBusy(false);
    }
  };

  const pause = () => setPlaying(false);

  const reset = async () => {
    setPlaying(false);
    setFinished(false);
    setError(null);
    await stopSession();
    distanceRef.current = 0;
    setDistance(0);
    const p = legsRef.current.length > 0 ? poseAtDistance(legsRef.current, 0) : null;
    setPose(p);
    setAlerts([]);
    setActiveHazardId(null);
    setCorridorNote(null);
  };

  const changeRoute = async (id: string) => {
    setPlaying(false);
    await stopSession();
    setAlerts([]);
    setActiveHazardId(null);
    setCorridorNote(null);
    setError(null);
    setFinished(false);
    setRouteId(id); // detail fetch effect resets distance + pose
  };

  // Clean up any server session when navigating away.
  useEffect(() => {
    return () => {
      if (sessionRef.current) {
        sessionRef.current = false;
        void api.post("/simulation/stop").catch(() => undefined);
      }
    };
  }, []);

  // --- Map inputs ----------------------------------------------------------------
  const hazardMarkers = useMemo<MapMarkerSpec[]>(() => {
    const items = hazards.data?.items ?? [];
    return items.map((h) => ({
      id: h.id,
      lat: h.latitude,
      lon: h.longitude,
      kind: `hazard-${h.status}`,
      selected: h.id === activeHazardId,
      label: `${h.status} · ×${h.report_count} reports`,
    }));
  }, [hazards.data, activeHazardId]);

  const radiusCircle = useMemo(
    () => (pose ? { lat: pose.lat, lon: pose.lon, radius_m: warning } : null),
    [pose, warning],
  );

  const progress = totalDistance > 0 ? Math.min(1, distance / totalDistance) : 0;
  const corridorAngle = settings.data?.defaults.sim_corridor_angle_deg;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="nb-page-title">Test a route against known hazards.</h1>
          <p className="mt-1 font-mono text-sm text-ink/70">
            Simulated vehicle — not live vehicle data. Position is interpolated locally along the
            demo route.
          </p>
        </div>
        <span className="nb-tag bg-accent-coral">
          <Square size={12} /> SIMULATED
        </span>
      </header>

      {error && (
        <div className="nb-card border-accent-coral bg-accent-coral/20 p-4 font-mono text-sm">
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        {/* Controls */}
        <aside className="nb-card flex h-fit flex-col gap-5 p-5">
          <h2 className="font-display text-sm font-bold uppercase">Playback controls</h2>

          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-xs font-bold uppercase text-ink/70">Route</span>
            <select
              className="nb-input"
              value={routeId}
              onChange={(e) => void changeRoute(e.target.value)}
            >
              <option value="">— Select demo route —</option>
              {routeItems.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-xs font-bold uppercase text-ink/70">
              Speed — {speed} m/s
            </span>
            <input
              type="range"
              min={1}
              max={40}
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
              className="accent-ink"
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-xs font-bold uppercase text-ink/70">
              Warning distance — {warning} m
            </span>
            <input
              type="range"
              min={20}
              max={500}
              step={10}
              value={warning}
              onChange={(e) => setWarning(Number(e.target.value))}
              className="accent-ink"
            />
            <span className="font-mono text-[10px] text-ink/60">
              Hazards within this radius can raise an alert.
            </span>
          </label>

          <div className="flex gap-2">
            <button
              className="nb-btn flex-1"
              disabled={!routeDetail || playing || busy}
              onClick={() => void play()}
              aria-label="Play"
            >
              <Play size={16} />
            </button>
            <button
              className="nb-btn nb-btn--secondary flex-1"
              disabled={!playing}
              onClick={pause}
              aria-label="Pause"
            >
              <Pause size={16} />
            </button>
            <button
              className="nb-btn nb-btn--danger flex-1"
              disabled={busy}
              onClick={() => void reset()}
              aria-label="Stop and reset"
            >
              <RotateCcw size={16} />
            </button>
          </div>

          {/* Progress */}
          <div className="flex flex-col gap-1.5">
            <div className="flex justify-between font-mono text-[11px] text-ink/70">
              <span>
                {(distance / 1000).toFixed(2)} / {(totalDistance / 1000).toFixed(2)} km
              </span>
              <span>{Math.round(progress * 100)}%</span>
            </div>
            <div className="h-4 border-[3px] border-ink bg-canvas">
              <div
                className="h-full bg-accent-mint transition-[width] duration-100"
                style={{ width: `${progress * 100}%` }}
              />
            </div>
          </div>

          {selected && (
            <p className="border-t-[3px] border-ink pt-3 font-mono text-xs text-ink/70">
              {selected.description ||
                `${selected.point_count} points · ${Math.round(selected.distance_m)} m`}
              {selected.is_synthetic && " · synthetic route"}
            </p>
          )}

          <p className="font-mono text-[10px] uppercase leading-relaxed text-ink/60">
            Forward corridor ±{corridorAngle ?? "60"}° heading filter — approximate, not a
            lane-level model. Resolved hazards never alert.
          </p>
        </aside>

        {/* Map + alert feed */}
        <div className="flex flex-col gap-6">
          <div className="nb-card overflow-hidden">
            <div className="relative h-[360px] lg:h-[440px]">
              <MapView
                markers={hazardMarkers}
                selectedId={activeHazardId}
                vehicle={pose}
                radiusCircle={radiusCircle}
                route={routePoints}
                fitKey={routeId}
                className="h-full"
                ariaLabel="Simulation map with route and hazards"
              />

              {/* Status overlay */}
              <div className="pointer-events-none absolute left-3 top-3 z-[900] flex flex-col items-start gap-2">
                <span className="nb-tag bg-surface">
                  {playing
                    ? "VEHICLE MOVING (SIMULATED)"
                    : finished
                      ? "ROUTE COMPLETE"
                      : routeDetail
                        ? "READY — PRESS PLAY"
                        : "SELECT A ROUTE"}
                </span>
                {playing && (
                  <span className="nb-tag animate-pulse bg-accent-yellow">
                    <Square size={10} /> SIMULATED POSITION
                  </span>
                )}
                {pose && (
                  <span className="nb-tag bg-accent-mint">
                    HEADING {pose.heading_deg.toFixed(0)}° · {speed} M/S
                  </span>
                )}
              </div>

              {!routeDetail && !error && (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-6">
                  <div className="nb-card bg-surface p-5">
                    <EmptyState
                      icon="◆"
                      title={routeId ? "Loading route…" : "No route selected"}
                      description="Pick a demo route to draw it on the map, then press play to drive the simulated vehicle past known hazards."
                    />
                  </div>
                </div>
              )}
            </div>

            <p className="flex items-center gap-2 border-t-[3px] border-ink bg-surface px-4 py-2 font-mono text-[10px] uppercase text-ink/70">
              <MapPin size={12} />
              Map tiles © OpenStreetMap contributors — tile requests reveal this viewport to the
              tile provider. Playback and alerts run locally.
            </p>
          </div>

          {/* Alert feed */}
          <section className="nb-card p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-display text-sm font-bold uppercase">Alert feed</h2>
              <div className="flex flex-wrap gap-2">
                <span className="nb-tag bg-accent-yellow">
                  <TriangleAlert size={12} /> {alerts.length} alert
                  {alerts.length === 1 ? "" : "s"} this session
                </span>
                <span className="nb-tag bg-canvas">NO REPEATS — DEDUPED PER RUN</span>
              </div>
            </div>

            {corridorNote && (
              <p className="mt-2 font-mono text-[10px] uppercase text-ink/60">
                {corridorNote} Distance uses Haversine; corridor is approximate.
              </p>
            )}

            <div className="mt-3 max-h-[320px] overflow-y-auto">
              {alerts.length === 0 ? (
                <EmptyState
                  icon="!"
                  title="No alerts yet"
                  description="Warnings appear here when the simulated vehicle enters the forward alert corridor of a hazard. Each hazard alerts at most once per run."
                />
              ) : (
                <ul className="flex flex-col gap-2">
                  {alerts.map((a, i) => (
                    <li
                      key={`${a.hazard_id}-${a.at}-${i}`}
                      className={`flex flex-wrap items-center gap-3 border-[3px] border-ink p-3 ${
                        i === 0 ? "bg-accent-yellow" : "bg-canvas"
                      }`}
                    >
                      <span className="font-mono text-[11px] text-ink/60">{a.at}</span>
                      <span className="font-display text-lg font-bold">
                        {Math.round(a.distance_m)} m
                      </span>
                      <span className={`nb-tag ${STATUS_BG[a.status] ?? "bg-surface"}`}>
                        {a.status}
                      </span>
                      <span className="font-mono text-xs">×{a.report_count} reports</span>
                      {a.confidence_avg != null && (
                        <span className="font-mono text-xs text-ink/70">
                          conf {a.confidence_avg.toFixed(2)}
                        </span>
                      )}
                      <span className="font-mono text-xs text-ink/70">
                        bearing {a.bearing_deg.toFixed(0)}°
                      </span>
                      {a.corridor_filtered && (
                        <span className="nb-tag bg-accent-blue">CORRIDOR ✓ (APPROX)</span>
                      )}
                      <button
                        className="nb-tag ml-auto bg-surface"
                        onClick={() => setActiveHazardId(a.hazard_id)}
                      >
                        HIGHLIGHT
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
