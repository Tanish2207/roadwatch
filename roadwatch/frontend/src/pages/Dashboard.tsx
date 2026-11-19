import { ArrowRight, MapPin, Video } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { usePoll } from "../hooks/usePoll";
import type { HazardSummary, JobSummary, Paginated } from "../types/api";

function KpiCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string | number;
  accent: string;
}) {
  return (
    <div className={`nb-card p-4 ${accent}`}>
      <div className="font-mono text-[11px] font-bold uppercase tracking-widest text-ink/70">
        {label}
      </div>
      <div className="font-display text-4xl font-bold">{value}</div>
    </div>
  );
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function Dashboard() {
  const jobs = usePoll<Paginated<JobSummary>>("/jobs?page=1&page_size=6", 6000);
  const hazards = usePoll<Paginated<HazardSummary>>("/hazards?page=1&page_size=6", 10000);

  const jobItems = jobs.data?.items ?? [];
  const hazardItems = hazards.data?.items ?? [];

  const detections = jobItems.reduce((sum, j) => sum + j.detections_count, 0);
  const processed = jobItems.filter((j) => j.status === "completed").length;
  const pending = jobItems.filter(
    (j) => j.status === "queued" || j.status === "processing" || j.status === "aggregating",
  ).length;

  return (
    <div className="flex flex-col gap-8">
      {/* Hero */}
      <section className="nb-card bg-accent-yellow p-6 md:p-8">
        <h1 className="nb-page-title">
          ROADWATCH <span className="text-ink/40">/</span> Roads, observed.
        </h1>
        <p className="mt-2 max-w-2xl font-mono text-sm">
          Local-first road-hazard detection. Dashcam footage never leaves this machine.
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          <Link to="/studio" className="nb-btn">
            <Video size={16} /> Upload dashcam clip
          </Link>
          <Link to="/map" className="nb-btn nb-btn--secondary">
            <MapPin size={16} /> Open hazard map
          </Link>
        </div>
      </section>

      {/* KPI tiles */}
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4" aria-label="Key metrics">
        <KpiCard label="Mapped hazards" value={hazards.data?.total ?? 0} accent="bg-accent-mint" />
        <KpiCard label="Detections" value={detections} accent="bg-accent-blue" />
        <KpiCard label="Videos processed" value={processed} accent="bg-accent-coral" />
        <KpiCard label="Jobs pending" value={pending} accent="bg-accent-yellow" />
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Recent jobs */}
        <section className="flex flex-col gap-4">
          <h2 className="font-display text-xl font-bold uppercase">Recent processing jobs</h2>
          {jobItems.length === 0 ? (
            <EmptyState
              icon="▶"
              title="No jobs yet"
              description="Your processed dashcam videos will appear here with status, progress and detection counts."
              action={
                <Link to="/studio" className="nb-btn mt-1">
                  Upload first clip <ArrowRight size={16} />
                </Link>
              }
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {jobItems.map((job) => (
                <li key={job.id} className="nb-card flex items-center gap-4 p-4">
                  <span
                    className={`nb-tag shrink-0 ${
                      job.status === "completed"
                        ? "bg-accent-mint"
                        : job.status === "failed"
                          ? "bg-accent-coral"
                          : "bg-accent-yellow"
                    }`}
                  >
                    {job.status}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-mono text-sm" title={job.original_filename}>
                    {job.original_filename}
                  </span>
                  <span className="shrink-0 font-mono text-xs text-ink/60">
                    {timeAgo(job.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Recent hazards + map preview */}
        <section className="flex flex-col gap-4">
          <h2 className="font-display text-xl font-bold uppercase">Recent hazard activity</h2>
          {hazardItems.length === 0 ? (
            <EmptyState
              icon="◆"
              title="No hazards published"
              description="Publish detections from Detection Studio to populate the local hazard network."
              action={
                <Link to="/map" className="nb-btn nb-btn--secondary mt-1">
                  <MapPin size={16} /> View map
                </Link>
              }
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {hazardItems.map((h) => (
                <li key={h.id} className="nb-card flex items-center gap-4 p-4">
                  <span
                    className={`nb-tag shrink-0 ${
                      h.status === "resolved" ? "bg-ink text-canvas" : "bg-accent-yellow"
                    }`}
                  >
                    {h.status}
                  </span>
                  <span className="min-w-0 flex-1 font-mono text-sm">
                    {h.latitude.toFixed(5)}, {h.longitude.toFixed(5)}
                  </span>
                  <span className="shrink-0 font-mono text-xs text-ink/60">
                    ×{h.report_count}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {/* Compact map preview placeholder */}
          <Link
            to="/map"
            className="nb-card group relative flex h-40 items-center justify-center overflow-hidden bg-accent-blue/30"
            aria-label="Open hazard map"
          >
            <div
              aria-hidden
              className="absolute inset-0 opacity-40"
              style={{
                backgroundImage:
                  "linear-gradient(#111 1px, transparent 1px), linear-gradient(90deg, #111 1px, transparent 1px)",
                backgroundSize: "32px 32px",
              }}
            />
            <span className="nb-tag relative bg-surface transition-transform group-hover:-translate-y-1">
              OPEN FULL MAP →
            </span>
          </Link>
        </section>
      </div>
    </div>
  );
}
