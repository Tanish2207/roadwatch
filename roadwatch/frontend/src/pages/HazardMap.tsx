import { ChevronRight, MapPin, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { MapView, type MapMarkerSpec } from "../components/MapView";
import { usePoll } from "../hooks/usePoll";
import type {
  HazardDetail,
  HazardStatus,
  HazardSummary,
  Paginated,
} from "../types/api";

const STATUS_OPTIONS: Array<HazardStatus | "all"> = [
  "all",
  "new",
  "observed",
  "confirmed",
  "resolved",
];

const TIME_OPTIONS: Array<{ value: string; label: string; hours: number | null }> = [
  { value: "all", label: "All time", hours: null },
  { value: "24h", label: "Last 24 h", hours: 24 },
  { value: "7d", label: "Last 7 days", hours: 168 },
  { value: "30d", label: "Last 30 days", hours: 720 },
];

const STATUS_BG: Record<HazardStatus, string> = {
  new: "bg-accent-yellow",
  observed: "bg-accent-blue",
  confirmed: "bg-accent-coral",
  resolved: "bg-ink text-canvas",
};

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

/** Hazard Map — filter panel + Leaflet map + detail drawer with status controls (M6). */
export function HazardMap() {
  const [status, setStatus] = useState<HazardStatus | "all">("all");
  const [timeRange, setTimeRange] = useState("all");
  const [minConfidence, setMinConfidence] = useState("");
  const [minReports, setMinReports] = useState("");

  // Debounce the numeric inputs so typing does not hammer the API.
  const [debounced, setDebounced] = useState({ confidence: "", reports: "" });
  useEffect(() => {
    const t = window.setTimeout(
      () => setDebounced({ confidence: minConfidence, reports: minReports }),
      400,
    );
    return () => window.clearTimeout(t);
  }, [minConfidence, minReports]);

  const query = useMemo(() => {
    const params = new URLSearchParams({ page: "1", page_size: "200" });
    if (status !== "all") params.set("status", status);
    if (debounced.confidence !== "") params.set("min_confidence", debounced.confidence);
    if (debounced.reports !== "") params.set("min_reports", debounced.reports);
    const hours = TIME_OPTIONS.find((t) => t.value === timeRange)?.hours;
    if (hours != null) params.set("seen_within_hours", String(hours));
    return `/hazards?${params.toString()}`;
  }, [status, timeRange, debounced]);

  const hazards = usePoll<Paginated<HazardSummary>>(query, 8000);
  const items = hazards.data?.items ?? [];

  // --- Detail drawer ---------------------------------------------------------
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<HazardDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [noteInput, setNoteInput] = useState("");
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    setNoteInput("");
    api
      .get<HazardDetail>(`/hazards/${selectedId}`)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setDetailError(err instanceof ApiError ? err.message : "Failed to load hazard");
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const updateStatus = async (next: HazardStatus) => {
    if (!detail) return;
    setUpdating(true);
    setDetailError(null);
    try {
      const updated = await api.patch<HazardDetail>(`/hazards/${detail.id}`, {
        status: next,
        note: noteInput.trim() || null,
      });
      setDetail(updated);
      setNoteInput("");
      await hazards.refresh();
    } catch (err) {
      setDetailError(err instanceof ApiError ? err.message : "Status update failed");
    } finally {
      setUpdating(false);
    }
  };

  /** Reopen target: the status held right before this hazard was resolved. */
  const reopenTarget = (detail?.status_history ?? []).find(
    (h) => h.new_status === "resolved",
  )?.previous_status as HazardStatus | null | undefined;

  // --- Map markers -----------------------------------------------------------
  const markers = useMemo<MapMarkerSpec[]>(
    () =>
      items.map((h) => ({
        id: h.id,
        lat: h.latitude,
        lon: h.longitude,
        kind: `hazard-${h.status}`,
        selected: h.id === selectedId,
        label: `${h.status} · ×${h.report_count} reports${
          h.confidence_avg != null ? ` · conf ${h.confidence_avg.toFixed(2)}` : ""
        }`,
      })),
    [items, selectedId],
  );

  // Refit only when the matching hazard set actually changes (not on every poll).
  const idsKey = items.map((h) => h.id).join(",");

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="nb-page-title">Hazards in the network</h1>
          <p className="mt-1 font-mono text-sm text-ink/70">
            Local prototype data — not a live global network.
          </p>
        </div>
        <span className="nb-tag bg-accent-yellow">
          <ShieldAlert size={12} /> LOCAL DEMO DATA
        </span>
      </header>

      {hazards.error && (
        <div className="nb-card border-accent-coral bg-accent-coral/20 p-4 font-mono text-sm">
          {hazards.error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
        {/* Filter panel */}
        <aside className="nb-card flex h-fit flex-col gap-5 p-5">
          <h2 className="font-display text-sm font-bold uppercase">Filters</h2>

          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 font-mono text-xs font-bold uppercase text-ink/70">Status</legend>
            {STATUS_OPTIONS.map((opt) => (
              <label key={opt} className="flex cursor-pointer items-center gap-2 font-mono text-sm">
                <input
                  type="radio"
                  name="status"
                  checked={status === opt}
                  onChange={() => setStatus(opt)}
                  className="accent-ink"
                />
                <span className="capitalize">{opt}</span>
              </label>
            ))}
          </fieldset>

          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-xs font-bold uppercase text-ink/70">
              Min confidence
            </span>
            <input
              className="nb-input"
              type="number"
              min={0}
              max={1}
              step={0.05}
              placeholder="0.00"
              value={minConfidence}
              onChange={(e) => setMinConfidence(e.target.value)}
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-xs font-bold uppercase text-ink/70">
              Min reports
            </span>
            <input
              className="nb-input"
              type="number"
              min={0}
              step={1}
              placeholder="0"
              value={minReports}
              onChange={(e) => setMinReports(e.target.value)}
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-xs font-bold uppercase text-ink/70">Time range</span>
            <select
              className="nb-input"
              value={timeRange}
              onChange={(e) => setTimeRange(e.target.value)}
            >
              {TIME_OPTIONS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>

          <button
            className="nb-btn nb-btn--secondary"
            onClick={() => {
              setStatus("all");
              setTimeRange("all");
              setMinConfidence("");
              setMinReports("");
            }}
          >
            Reset filters
          </button>

          <div className="border-t-[3px] border-ink pt-3 font-mono text-xs text-ink/70">
            {hazards.loading && !hazards.data
              ? "Loading..."
              : `${hazards.data?.total ?? 0} hazard(s) match`}
          </div>
        </aside>

        {/* Map area */}
        <div className="relative">
          <div className="nb-card overflow-hidden">
            <div className="relative h-[440px] lg:h-[580px]">
              <MapView
                markers={markers}
                selectedId={selectedId}
                onMarkerClick={(id) => setSelectedId(id)}
                cluster
                fitKey={idsKey}
                className="h-full"
                ariaLabel="Map of local hazards"
              />

              {hazards.loading && !hazards.data && (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                  <span className="nb-tag bg-surface">LOADING HAZARDS…</span>
                </div>
              )}

              {!hazards.loading && !hazards.error && items.length === 0 && (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-6">
                  <div className="nb-card max-w-sm bg-surface p-5">
                    <EmptyState
                      icon="◆"
                      title="No hazards match"
                      description="Publish detections from Detection Studio — or relax the filters — and hazards appear as markers here, deduplicated automatically."
                    />
                  </div>
                </div>
              )}

              {/* Detail drawer */}
              {selectedId && (
                <aside className="nb-card absolute right-3 top-3 bottom-3 z-[1000] flex w-[min(360px,calc(100%-1.5rem))] flex-col gap-3 overflow-y-auto bg-surface p-5">
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="font-display text-base font-bold uppercase">Hazard detail</h3>
                    <button
                      className="nb-tag bg-canvas"
                      onClick={() => setSelectedId(null)}
                      aria-label="Close detail"
                    >
                      ✕
                    </button>
                  </div>

                  {detailLoading && <p className="font-mono text-xs">Loading detail…</p>}
                  {detailError && (
                    <p className="border-[3px] border-accent-coral bg-accent-coral/20 p-2 font-mono text-xs">
                      {detailError}
                    </p>
                  )}

                  {detail && (
                    <>
                      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 font-mono text-xs">
                        <dt className="text-ink/60">ID</dt>
                        <dd className="truncate" title={detail.id}>
                          {detail.id}
                        </dd>
                        <dt className="text-ink/60">Location</dt>
                        <dd>
                          {detail.latitude.toFixed(5)}, {detail.longitude.toFixed(5)}
                        </dd>
                        <dt className="text-ink/60">Status</dt>
                        <dd>
                          <span className={`nb-tag ${STATUS_BG[detail.status]}`}>
                            {detail.status}
                          </span>
                          {detail.is_stale && <span className="nb-tag ml-1 bg-canvas">stale</span>}
                        </dd>
                        <dt className="text-ink/60">Reports</dt>
                        <dd>×{detail.report_count}</dd>
                        <dt className="text-ink/60">Confidence</dt>
                        <dd>
                          avg {detail.confidence_avg != null ? detail.confidence_avg.toFixed(2) : "—"}
                          {" · max "}
                          {detail.confidence_max != null ? detail.confidence_max.toFixed(2) : "—"}
                        </dd>
                        <dt className="text-ink/60">First seen</dt>
                        <dd>{fmtTime(detail.first_seen_at)}</dd>
                        <dt className="text-ink/60">Last seen</dt>
                        <dd>{fmtTime(detail.last_seen_at)}</dd>
                        {detail.resolved_at && (
                          <>
                            <dt className="text-ink/60">Resolved</dt>
                            <dd>{fmtTime(detail.resolved_at)}</dd>
                          </>
                        )}
                      </dl>

                      <p className="border-t-[3px] border-ink pt-2 font-mono text-[10px] uppercase text-ink/60">
                        Approximate location · uncertainty{" "}
                        {detail.location_uncertainty_m != null
                          ? `±${Math.round(detail.location_uncertainty_m)} m`
                          : "unknown"}
                      </p>

                      {/* Status update controls */}
                      <div className="flex flex-col gap-2 border-t-[3px] border-ink pt-3">
                        <label className="flex flex-col gap-1.5">
                          <span className="font-mono text-xs font-bold uppercase text-ink/70">
                            Note (optional)
                          </span>
                          <input
                            className="nb-input"
                            type="text"
                            placeholder="e.g. repaired by crew A"
                            value={noteInput}
                            onChange={(e) => setNoteInput(e.target.value)}
                          />
                        </label>
                        <div className="flex gap-2">
                          {detail.status !== "resolved" ? (
                            <button
                              className="nb-btn nb-btn--danger flex-1 text-xs"
                              disabled={updating}
                              onClick={() => void updateStatus("resolved")}
                            >
                              <ShieldAlert size={14} /> Mark resolved
                            </button>
                          ) : (
                            <button
                              className="nb-btn flex-1 text-xs"
                              disabled={updating}
                              onClick={() =>
                                void updateStatus(
                                  (reopenTarget && reopenTarget !== "resolved"
                                    ? reopenTarget
                                    : "observed") as HazardStatus,
                                )
                              }
                            >
                              <ChevronRight size={14} /> Reopen
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Observations */}
                      <section className="border-t-[3px] border-ink pt-3">
                        <h4 className="font-display text-xs font-bold uppercase">
                          Observations ({detail.observations_total})
                        </h4>
                        {detail.observations.length === 0 ? (
                          <p className="mt-1 font-mono text-xs text-ink/60">
                            No linked observations (hazard may come from a re-aggregated publish).
                          </p>
                        ) : (
                          <ul className="mt-2 flex flex-col gap-1.5 font-mono text-[11px]">
                            {detail.observations.slice(0, 6).map((o) => (
                              <li key={o.id} className="flex justify-between gap-2">
                                <span className="truncate" title={o.job_id}>
                                  {o.job_id.slice(0, 8)} · t={o.frame_timestamp_seconds.toFixed(1)}s
                                </span>
                                <span className="shrink-0 font-bold">
                                  {o.class_name} {o.confidence.toFixed(2)}
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                        {detail.observations_total > 6 && (
                          <p className="mt-1 font-mono text-[10px] text-ink/60">
                            Showing 6 of {detail.observations_total} observations.
                          </p>
                        )}
                      </section>

                      {/* Status history */}
                      <section className="border-t-[3px] border-ink pt-3">
                        <h4 className="font-display text-xs font-bold uppercase">Status history</h4>
                        {detail.status_history.length === 0 ? (
                          <p className="mt-1 font-mono text-xs text-ink/60">
                            No status changes yet.
                          </p>
                        ) : (
                          <ul className="mt-2 flex flex-col gap-1.5 font-mono text-[11px]">
                            {detail.status_history.slice(0, 5).map((h) => (
                              <li key={h.id}>
                                <span className="font-bold">
                                  {h.previous_status ? `${h.previous_status} → ` : ""}
                                  {h.new_status}
                                </span>
                                {h.note && <span className="text-ink/70"> — {h.note}</span>}
                                <span className="block text-[10px] text-ink/50">
                                  {fmtTime(h.created_at)}
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                        {detail.status_history.length > 5 && (
                          <p className="mt-1 font-mono text-[10px] text-ink/60">
                            Showing 5 of {detail.status_history.length} entries.
                          </p>
                        )}
                      </section>
                    </>
                  )}
                </aside>
              )}
            </div>

            {/* Tile-provider disclosure (brief §13) */}
            <p className="flex items-center gap-2 border-t-[3px] border-ink bg-surface px-4 py-2 font-mono text-[10px] uppercase text-ink/70">
              <MapPin size={12} />
              Map tiles © OpenStreetMap contributors — tile requests reveal this viewport to the
              tile provider. All hazard data stays local.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
