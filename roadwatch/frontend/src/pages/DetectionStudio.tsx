import { Play, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import type {
  DetectionOut,
  FrameEntry,
  FrameManifest,
  HealthResponse,
  JobSummary,
  Paginated,
  SettingsResponse,
} from "../types/api";

type Phase = "idle" | "uploading" | "tracking" | "done" | "error";

const POLL_MS = 1500;
/** localStorage key remembering the active job across page refreshes. */
const ACTIVE_JOB_KEY = "roadwatch.active_job";

export function DetectionStudio() {
  const settings = usePoll<SettingsResponse>("/settings", 30000);
  const health = usePoll<HealthResponse>("/health", 15000);

  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [gpsFile, setGpsFile] = useState<File | null>(null);
  const [sampleRate, setSampleRate] = useState(1);
  const [threshold, setThreshold] = useState(0.4);
  const [imageSize, setImageSize] = useState(640);

  const [phase, setPhase] = useState<Phase>("idle");
  const [job, setJob] = useState<JobSummary | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [detections, setDetections] = useState<DetectionOut[]>([]);
  const [detTotal, setDetTotal] = useState(0);
  const [publishMsg, setPublishMsg] = useState<string | null>(null);
  const [frames, setFrames] = useState<FrameEntry[]>([]);
  const [framesLoading, setFramesLoading] = useState(false);
  const [selFrame, setSelFrame] = useState(0);
  /** While processing: follow the newest annotated frame ("live feed"). */
  const [followLive, setFollowLive] = useState(true);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pollRef = useRef<number | null>(null);
  const followLiveRef = useRef(true);

  const modelReady = health.data?.model.ready ?? false;
  const allowedVideo = settings.data?.limits.allowed_video_extensions.join(", ") ?? ".mp4";

  const setLiveFollow = (on: boolean) => {
    followLiveRef.current = on;
    setFollowLive(on);
  };

  const stopPolling = () => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => stopPolling, []);

  /** Fetch detections + annotated frames for a finished job. */
  const loadResults = useCallback(async (jobId: string) => {
    const dets = await api.get<Paginated<DetectionOut>>(
      `/jobs/${jobId}/detections?page=1&page_size=200`,
    );
    setDetections(dets.items);
    setDetTotal(dets.total);

    // Annotated frames for the split viewer (backfills past clips
    // on the server; non-fatal if unavailable).
    setFramesLoading(true);
    try {
      const fm = await api.get<FrameManifest>(`/jobs/${jobId}/frames`);
      setFrames(fm.items);
      // Keep the current selection if it still exists (a pinned frame or the
      // live-followed one); otherwise fall back to the first frame.
      setSelFrame((prev) =>
        fm.items.some((f) => f.ordinal === prev)
          ? prev
          : fm.items.length > 0
            ? fm.items[0].ordinal
            : 0,
      );
    } catch {
      setFrames([]);
    } finally {
      setFramesLoading(false);
    }
  }, []);

  const trackJob = useCallback((jobId: string) => {
    setPhase("tracking");
    stopPolling();
    pollRef.current = window.setInterval(async () => {
      try {
        const j = await api.get<JobSummary>(`/jobs/${jobId}`);
        setJob(j);
        if (j.status === "completed" || j.status === "failed" || j.status === "cancelled") {
          stopPolling();
          if (j.status === "completed") {
            setPhase("done");
            await loadResults(jobId);
          } else {
            setPhase("error");
            setErrorMsg(j.error_message ?? `Job ${j.status}.`);
          }
        } else {
          // Job still running: stream annotated frames as they are produced
          // (the worker persists them + rewrites the manifest during inference)
          try {
            const fm = await api.get<FrameManifest>(`/jobs/${jobId}/frames`);
            if (fm.items.length > 0) {
              const newest = fm.items[fm.items.length - 1].ordinal;
              setFrames(fm.items);
              setSelFrame((prev) => (followLiveRef.current ? newest : prev));
            }
          } catch {
            /* live frames are best-effort; job polling continues */
          }
        }
      } catch (err) {
        stopPolling();
        setPhase("error");
        setErrorMsg(err instanceof ApiError ? err.message : "Lost contact with backend.");
      }
    }, POLL_MS);
  }, [loadResults]);

  // Restore the active job after a page refresh so progress never disappears.
  useEffect(() => {
    const savedId = window.localStorage.getItem(ACTIVE_JOB_KEY);
    if (!savedId) return;
    let stale = false;
    (async () => {
      try {
        const j = await api.get<JobSummary>(`/jobs/${savedId}`);
        if (stale) return;
        setJob(j);
        if (j.status === "completed") {
          setPhase("done");
          await loadResults(j.id);
        } else if (j.status === "failed" || j.status === "cancelled") {
          setPhase("error");
          setErrorMsg(j.error_message ?? `Job ${j.status}.`);
        } else {
          trackJob(j.id); // still queued/processing: resume live tracking
        }
      } catch (err) {
        // Job was deleted (404) -> forget it. Network errors keep the id so
        // a later refresh can resume once the backend is back.
        if (err instanceof ApiError && err.status === 404) {
          window.localStorage.removeItem(ACTIVE_JOB_KEY);
        } else {
          setPhase("error");
          setErrorMsg(err instanceof ApiError ? err.message : "Lost contact with backend.");
        }
      }
    })();
    return () => {
      stale = true;
    };
  }, [loadResults, trackJob]);

  const startProcessing = async () => {
    if (!videoFile) return;
    setPhase("uploading");
    setErrorMsg(null);
    setPublishMsg(null);
    setJob(null);
    setDetections([]);
    setDetTotal(0);
    setFrames([]);
    setSelFrame(0);
    setLiveFollow(true);

    try {
      const form = new FormData();
      form.append("video", videoFile);
      if (gpsFile) form.append("gps_csv", gpsFile);
      form.append("sample_rate_fps", String(sampleRate));
      form.append("confidence_threshold", String(threshold));
      form.append("image_size", String(imageSize));

      const created = await api.post<JobSummary>("/jobs", form);
      // Remember across refreshes so the job (and its progress) survives
      window.localStorage.setItem(ACTIVE_JOB_KEY, created.id);
      setJob(created);
      trackJob(created.id);
    } catch (err) {
      setPhase("error");
      setErrorMsg(err instanceof ApiError ? err.message : "Upload failed.");
    }
  };

  const cancelJob = async () => {
    if (!job) return;
    try {
      const j = await api.post<JobSummary>(`/jobs/${job.id}/cancel`);
      setJob(j);
      stopPolling();
      setPhase(j.status === "cancelled" ? "error" : "tracking");
      if (j.status === "cancelled") setErrorMsg("Job cancelled.");
      else trackJob(job.id);
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : "Cancel failed.");
    }
  };

  const publish = async () => {
    if (!job) return;
    setPublishMsg(null);
    try {
      const res = await api.post<{ status: string; published_hazards: number }>(
        `/jobs/${job.id}/publish`,
      );
      setPublishMsg(
        `✓ ${res.published_hazards} hazard(s) ${res.status === "published" ? "published to" : "already on"} the map.`,
      );
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : "Publish failed.");
    }
  };

  const reset = () => {
    stopPolling();
    window.localStorage.removeItem(ACTIVE_JOB_KEY);
    setPhase("idle");
    setJob(null);
    setVideoFile(null);
    setGpsFile(null);
    setErrorMsg(null);
    setPublishMsg(null);
    setDetections([]);
    setDetTotal(0);
    setFrames([]);
    setFramesLoading(false);
    setSelFrame(0);
    setLiveFollow(true);
  };

  const progress = job?.progress_percent ?? 0;
  const busy = phase === "uploading" || phase === "tracking";

  // -- Split viewer: video <-> annotated frame sync -------------------------
  const sel = frames.find((f) => f.ordinal === selFrame) ?? frames[0];

  const seekToFrame = (f: FrameEntry) => {
    if (busy) setLiveFollow(false); // inspecting pauses the live feed
    setSelFrame(f.ordinal);
    const v = videoRef.current;
    if (v && Math.abs(v.currentTime - f.timestamp_s) > 0.05) {
      v.currentTime = f.timestamp_s;
    }
  };

  const resumeLive = () => {
    setLiveFollow(true);
    if (frames.length > 0) setSelFrame(frames[frames.length - 1].ordinal);
  };

  const onTimeUpdate = () => {
    // While processing, the right pane is the live inference feed; the
    // playhead-follow takes over once the job is done.
    if (busy) return;
    const v = videoRef.current;
    if (!v || frames.length === 0) return;
    const t = v.currentTime;
    // Show the annotated frame nearest to (at or just before) the playhead
    let idx = 0;
    for (let i = 0; i < frames.length; i++) {
      if (frames[i].timestamp_s <= t + 0.15) idx = i;
      else break;
    }
    const ord = frames[idx].ordinal;
    setSelFrame((prev) => (prev === ord ? prev : ord));
  };

  return (
    <div className="flex flex-col gap-8">
      <header className="nb-card bg-accent-blue p-6 md:p-8">
        <h1 className="nb-page-title">Drop a dashcam clip. Find the hazards.</h1>
        <p className="mt-2 font-mono text-sm">
          MP4 preferred · GPS sidecar CSV optional · inference runs locally
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* ---- Source files ---- */}
        <section className="nb-card flex flex-col gap-5 p-6">
          <h2 className="font-display text-lg font-bold uppercase">1 · Source files</h2>

          <label
            className={`flex cursor-pointer flex-col items-center gap-2 border-[3px] border-dashed border-ink px-4 py-8 text-center transition-colors ${
              videoFile ? "bg-accent-mint" : "bg-canvas hover:bg-accent-yellow/40"
            }`}
          >
            <Upload size={26} />
            <span className="font-display text-sm font-bold uppercase">
              {videoFile?.name ?? "Select video file"}
            </span>
            <span className="font-mono text-[11px] text-ink/60">Accepted: {allowedVideo}</span>
            <input
              type="file"
              className="sr-only"
              accept={settings.data?.limits.allowed_video_extensions.join(",") ?? undefined}
              disabled={busy}
              onChange={(e) => setVideoFile(e.target.files?.[0] ?? null)}
            />
          </label>

          <label
            className={`flex cursor-pointer flex-col items-center gap-2 border-[3px] border-dashed border-ink px-4 py-6 text-center transition-colors ${
              gpsFile ? "bg-accent-mint" : "bg-canvas hover:bg-accent-yellow/40"
            }`}
          >
            <span className="font-display text-sm font-bold uppercase">
              {gpsFile?.name ?? "GPS sidecar CSV (optional)"}
            </span>
            <span className="font-mono text-[11px] text-ink/60">
              timestamp,latitude,longitude[,speed_mps,heading_deg]
            </span>
            <input
              type="file"
              className="sr-only"
              accept=".csv"
              disabled={busy}
              onChange={(e) => setGpsFile(e.target.files?.[0] ?? null)}
            />
          </label>

          {!gpsFile && (
            <p className="nb-tag bg-accent-yellow self-start">
              No GPS → detections cannot be mapped
            </p>
          )}
        </section>

        {/* ---- Options ---- */}
        <section className="nb-card flex flex-col gap-5 p-6">
          <h2 className="font-display text-lg font-bold uppercase">2 · Processing options</h2>

          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-xs font-bold uppercase">
              Frame sampling — {sampleRate} fps
            </span>
            <input
              type="range"
              min={0.5}
              max={5}
              step={0.5}
              value={sampleRate}
              disabled={busy}
              onChange={(e) => setSampleRate(Number(e.target.value))}
              className="accent-ink"
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-xs font-bold uppercase">
              Confidence threshold — {threshold.toFixed(2)}
            </span>
            <input
              type="range"
              min={0.1}
              max={0.9}
              step={0.05}
              value={threshold}
              disabled={busy}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="accent-ink"
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-xs font-bold uppercase">Image size</span>
            <select
              className="nb-input"
              value={imageSize}
              disabled={busy}
              onChange={(e) => setImageSize(Number(e.target.value))}
            >
              <option value={320}>320 px (fast)</option>
              <option value={640}>640 px (default)</option>
              <option value={1280}>1280 px (accurate)</option>
            </select>
          </label>

          <div className="mt-auto flex flex-col gap-3">
            {!modelReady && (
              <p className="nb-tag bg-accent-yellow self-start">
                Model weights not loaded — see Settings
              </p>
            )}
            <div className="flex gap-3">
              <button
                className="nb-btn flex-1"
                disabled={!videoFile || busy || !modelReady}
                onClick={startProcessing}
              >
                <Play size={16} /> {busy ? "Working…" : "Start processing"}
              </button>
              <button className="nb-btn nb-btn--secondary" disabled={busy} onClick={reset}>
                Clear
              </button>
            </div>
            {job && (
              <button className="nb-btn nb-btn--danger" disabled={!busy} onClick={cancelJob}>
                Cancel job
              </button>
            )}
          </div>
        </section>
      </div>

      {/* ---- Error with no job to show (e.g. restore failed, backend down) ---- */}
      {phase === "error" && !job && errorMsg && (
        <section className="nb-card flex flex-col gap-3 p-6">
          <h2 className="font-display text-lg font-bold uppercase">Job status</h2>
          <p className="border-[3px] border-ink bg-accent-coral p-3 font-mono text-sm">
            {errorMsg}
          </p>
          <button
            className="nb-btn nb-btn--secondary self-start"
            onClick={() => {
              setErrorMsg(null);
              setPhase("idle");
            }}
          >
            Dismiss
          </button>
        </section>
      )}

      {/* ---- Progress ---- */}
      {(busy || phase === "done" || phase === "error") && job && (
        <section className="nb-card flex flex-col gap-4 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-display text-lg font-bold uppercase">Job status</h2>
            <span
              className={`nb-tag ${
                job.status === "completed"
                  ? "bg-accent-mint"
                  : job.status === "failed" || job.status === "cancelled"
                    ? "bg-accent-coral"
                    : "bg-accent-yellow"
              }`}
            >
              {job.status}
            </span>
          </div>

          {/* Progress bar */}
          <div
            className="h-8 w-full border-[3px] border-ink bg-canvas"
            role="progressbar"
            aria-valuenow={progress}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-full bg-accent-yellow transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>

          <div className="grid grid-cols-2 gap-3 font-mono text-sm md:grid-cols-4">
            <div>
              <span className="block text-xs uppercase text-ink/60">Progress</span>
              <b>{progress}%</b>
            </div>
            <div>
              <span className="block text-xs uppercase text-ink/60">Frames sampled</span>
              <b>{job.frames_processed}</b>
            </div>
            <div>
              <span className="block text-xs uppercase text-ink/60">Detections</span>
              <b>{job.detections_count}</b>
            </div>
            <div>
              <span className="block text-xs uppercase text-ink/60">File</span>
              <b className="truncate block" title={job.original_filename}>
                {job.original_filename}
              </b>
            </div>
          </div>

          {job.error_message && (
            <p className="border-[3px] border-ink bg-accent-yellow p-3 font-mono text-xs">
              {job.error_message}
            </p>
          )}
          {errorMsg && (
            <p className="border-[3px] border-ink bg-accent-coral p-3 font-mono text-xs">
              {errorMsg}
            </p>
          )}
        </section>
      )}

      {/* ---- Split viewer: shown live during processing and after ---- */}
      {job && (busy || phase === "done") && (
          <section className="nb-card flex flex-col gap-4 p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-display text-lg font-bold uppercase">
                {busy ? "Live: original vs YOLO-annotated" : "Original vs YOLO-annotated"}
              </h2>
              <div className="flex flex-wrap items-center gap-2">
                {busy && (
                  <span className={`nb-tag ${followLive ? "bg-accent-coral" : "bg-canvas"}`}>
                    <span
                      className={`mr-1 inline-block h-2 w-2 rounded-full ${
                        followLive ? "animate-pulse bg-white" : "bg-ink/40"
                      }`}
                    />
                    {followLive ? "live" : "paused"}
                  </span>
                )}
                {busy && !followLive && (
                  <button
                    type="button"
                    className="nb-tag bg-accent-mint hover:bg-accent-yellow"
                    onClick={resumeLive}
                  >
                    ▶ resume live
                  </button>
                )}
                <span className="nb-tag bg-accent-mint">
                  {framesLoading
                    ? "preparing frames..."
                    : frames.length > 0
                      ? busy
                        ? `${frames.length} frames processed so far`
                        : `${frames.length} processed frames stored`
                      : busy
                        ? "waiting for first processed frame..."
                        : "no frames"}
                </span>
              </div>
            </div>

            {framesLoading ? (
              <p className="border-[3px] border-ink bg-canvas p-4 font-mono text-sm text-ink/70">
                Loading annotated frames for this clip…
              </p>
            ) : frames.length === 0 || !sel ? (
              <p className="border-[3px] border-ink bg-canvas p-4 font-mono text-sm text-ink/70">
                {busy
                  ? "The model is warming up — annotated frames will appear here as soon as they are produced."
                  : "No annotated frames available for this clip yet."}
              </p>
            ) : (
              <>
                <div className="grid gap-4 lg:grid-cols-2">
                  {/* LEFT: original video */}
                  <div className="flex min-w-0 flex-col gap-2">
                    <span className="nb-tag bg-accent-yellow self-start">
                      ▶ Original video
                    </span>
                    <video
                      ref={videoRef}
                      src={`/api/jobs/${job.id}/source`}
                      controls
                      playsInline
                      preload="metadata"
                      onTimeUpdate={onTimeUpdate}
                      className="max-h-[520px] w-full border-[3px] border-ink bg-ink"
                    />
                  </div>

                  {/* RIGHT: annotated frame */}
                  <div className="flex min-w-0 flex-col gap-2">
                    <span className="nb-tag bg-accent-blue self-start">
                      🎯 YOLO output — T+{sel.timestamp_s.toFixed(1)}s
                    </span>
                    <div className="relative border-[3px] border-ink bg-ink">
                      <img
                        src={sel.image_url}
                        alt={`Annotated frame at ${sel.timestamp_s} seconds with ${sel.detections} detection(s)`}
                        className="max-h-[520px] w-full object-contain"
                      />
                      <span
                        className={`absolute left-2 top-2 nb-tag ${
                          sel.detections > 0 ? "bg-accent-yellow" : "bg-canvas"
                        }`}
                      >
                        {sel.detections} detection{sel.detections === 1 ? "" : "s"}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Filmstrip: click a frame -> seek both panes */}
                <div className="flex gap-2 overflow-x-auto border-[3px] border-ink bg-canvas p-2">
                  {frames.map((f) => (
                    <button
                      key={f.ordinal}
                      type="button"
                      onClick={() => seekToFrame(f)}
                      title={`Frame ${f.ordinal + 1} · T+${f.timestamp_s}s · ${f.detections} detection(s)`}
                      className={`relative shrink-0 border-[3px] transition-colors ${
                        f.ordinal === selFrame
                          ? "border-accent-coral"
                          : "border-ink/25 hover:border-ink"
                      }`}
                    >
                      <img
                        src={f.image_url}
                        loading="lazy"
                        alt=""
                        className="block h-16 w-auto"
                      />
                      <span className="absolute bottom-0 right-0 bg-ink px-1 font-mono text-[9px] leading-4 text-white">
                        {f.timestamp_s.toFixed(0)}s
                      </span>
                      {f.detections > 0 && (
                        <span className="absolute left-0 top-0 bg-ink px-1 font-mono text-[9px] leading-4 text-accent-yellow">
                          {f.detections}×
                        </span>
                      )}
                    </button>
                  ))}
                </div>

                <p className="font-mono text-[11px] text-ink/60">
                  Play the original on the left — the YOLO frame on the right follows the
                  playhead. Click any thumbnail to jump both panes to that moment.
                  Frames are stored on disk and persist for past processed clips.
                </p>
              </>
            )}
          </section>
      )}

      {/* ---- Results (detections, artifacts, publish) ---- */}
      {phase === "done" && job && (
          <section className="grid gap-6 lg:grid-cols-2">
          {/* Preview / artifact */}
          <div className="nb-card flex flex-col gap-4 p-6">
            <h2 className="font-display text-lg font-bold uppercase">Annotated output</h2>
            <img
              src={`/api/jobs/${job.id}/preview`}
              alt="First annotated frame with detections"
              className="w-full border-[3px] border-ink object-contain"
              onError={(e) => {
                (e.currentTarget as HTMLImageElement).style.display = "none";
              }}
            />
            <a className="nb-btn" href={`/api/jobs/${job.id}/artifact`} download>
              Download annotated video
            </a>
            <div className="flex flex-wrap gap-3">
              <button
                className="nb-btn nb-btn--secondary flex-1"
                disabled={detTotal === 0 || !!publishMsg}
                onClick={publish}
              >
                Publish to map
              </button>
            </div>
            {publishMsg && (
              <p className="border-[3px] border-ink bg-accent-mint p-3 font-mono text-sm">
                {publishMsg}
              </p>
            )}
          </div>

          {/* Detection list */}
          <div className="nb-card flex flex-col gap-4 p-6">
            <h2 className="font-display text-lg font-bold uppercase">
              Detections ({detTotal})
            </h2>
            <div className="max-h-[420px] overflow-y-auto">
              {detections.length === 0 ? (
                <p className="font-mono text-sm text-ink/60">
                  No detections above the threshold. Try lowering the confidence threshold.
                </p>
              ) : (
                <table className="w-full border-collapse font-mono text-xs">
                  <thead>
                    <tr className="border-b-[3px] border-ink text-left uppercase">
                      <th className="py-2 pr-2">T (s)</th>
                      <th className="py-2 pr-2">Class</th>
                      <th className="py-2 pr-2">Conf</th>
                      <th className="py-2">GPS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detections.map((d) => (
                      <tr key={d.id} className="border-b border-ink/15">
                        <td className="py-1.5 pr-2">{d.frame_timestamp_seconds.toFixed(1)}</td>
                        <td className="py-1.5 pr-2 uppercase">{d.class_name}</td>
                        <td className="py-1.5 pr-2">{d.confidence.toFixed(2)}</td>
                        <td className="py-1.5">
                          {d.gps_lat != null ? (
                            <span
                              className={`nb-tag ${
                                d.gps_match_method === "none" ? "bg-accent-coral" : "bg-accent-mint"
                              }`}
                              title={`${d.gps_match_method} (Δ${d.gps_match_delta_seconds ?? "?"}s)`}
                            >
                              {d.gps_lat.toFixed(5)}, {d.gps_lon!.toFixed(5)}
                            </span>
                          ) : (
                            <span className="nb-tag bg-accent-coral">no match</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
