import { Cpu, HardDrive, Lock, TriangleAlert } from "lucide-react";
import { usePoll } from "../hooks/usePoll";
import type { HealthResponse, SettingsResponse } from "../types/api";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-ink/15 py-2 last:border-0">
      <span className="font-mono text-xs uppercase text-ink/60">{label}</span>
      <span className="font-mono text-sm font-bold">{value}</span>
    </div>
  );
}

export function Settings() {
  const settings = usePoll<SettingsResponse>("/settings", 15000);
  const health = usePoll<HealthResponse>("/health", 10000);

  const s = settings.data;
  const model = health.data?.model;

  return (
    <div className="flex flex-col gap-6">
      <header className="nb-card bg-accent-mint p-6 md:p-8">
        <h1 className="nb-page-title">Settings</h1>
        <p className="mt-2 font-mono text-sm">Local model, inference defaults and privacy.</p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Model */}
        <section className="nb-card flex flex-col gap-4 p-6">
          <h2 className="flex items-center gap-2 font-display text-lg font-bold uppercase">
            <Cpu size={18} /> Model
          </h2>

          {settings.error ? (
            <p className="nb-tag bg-accent-coral self-start">{settings.error}</p>
          ) : (
            <>
              <div
                className={`nb-tag self-start ${model?.ready ? "bg-accent-mint" : "bg-accent-coral"}`}
              >
                {model?.ready ? "READY" : "NOT LOADED"}
              </div>
              <div>
                <Row label="Weights file" value={model?.filename ?? "—"} />
                <Row label="Source" value={model?.source ?? "—"} />
                <Row label="Classes" value={model?.classes?.join(", ") ?? "loaded on demand"} />
              </div>
              {!model?.ready && model?.hint && (
                <p className="flex items-start gap-2 border-[3px] border-ink bg-accent-yellow p-3 font-mono text-xs">
                  <TriangleAlert size={14} className="mt-0.5 shrink-0" />
                  {model.hint}
                </p>
              )}
            </>
          )}
        </section>

        {/* Inference defaults */}
        <section className="nb-card flex flex-col gap-4 p-6">
          <h2 className="font-display text-lg font-bold uppercase">Inference defaults</h2>
          {s ? (
            <div>
              <Row label="Frame sampling" value={`${s.defaults.sample_rate_fps} fps`} />
              <Row label="Confidence threshold" value={String(s.defaults.confidence_threshold)} />
              <Row label="Image size" value={`${s.defaults.image_size} px`} />
              <Row
                label="GPS tolerance"
                value={`±${s.defaults.gps_max_tolerance_seconds} s`}
              />
              <Row label="Aggregation radius" value={`${s.defaults.aggregation_radius_m} m`} />
              <Row label="Max upload" value={`${s.limits.max_upload_mb} MB`} />
              <Row
                label="Video types"
                value={s.limits.allowed_video_extensions.join(" ")}
              />
            </div>
          ) : (
            <p className="font-mono text-sm text-ink/60">Loading…</p>
          )}
          <p className="font-mono text-[11px] text-ink/60">
            Edit via ROADWATCH_* variables in <span className="font-bold">.env</span>; per-job
            overrides are available when creating a job.
          </p>
        </section>

        {/* Storage */}
        <section className="nb-card flex flex-col gap-4 p-6">
          <h2 className="flex items-center gap-2 font-display text-lg font-bold uppercase">
            <HardDrive size={18} /> Storage
          </h2>
          {s ? (
            <div>
              <Row label="Uploads" value={s.storage.uploads_dir} />
              <Row label="Processed output" value={s.storage.processed_dir} />
            </div>
          ) : (
            <p className="font-mono text-sm text-ink/60">Loading…</p>
          )}
          <p className="font-mono text-[11px] text-ink/60">
            Delete-job (retention cleanup) arrives with the processing milestone.
          </p>
        </section>

        {/* Privacy */}
        <section className="nb-card flex flex-col gap-4 p-6">
          <h2 className="flex items-center gap-2 font-display text-lg font-bold uppercase">
            <Lock size={18} /> Privacy & local processing
          </h2>
          <p className="nb-tag bg-accent-mint self-start">
            {s?.privacy.statement ?? "LOCAL INFERENCE · VIDEO STAYS ON THIS MACHINE"}
          </p>
          <p className="font-mono text-xs leading-relaxed text-ink/70">
            Video, frames, GPS and inference never leave this machine. No cloud AI services are
            used. External dependencies: OpenStreetMap map tiles — loading a map reveals your map
            viewport to the tile provider ({s?.privacy.tile_provider ?? "…"}).
          </p>
          <p className="font-mono text-xs leading-relaxed text-ink/70">
            RoadWatch alerts are experimental and must not be the sole basis for driving decisions.
            Do not interact with the app while driving.
          </p>
        </section>
      </div>
    </div>
  );
}
