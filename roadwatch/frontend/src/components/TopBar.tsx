import { Activity, Cpu, Menu, X } from "lucide-react";
import { usePoll } from "../hooks/usePoll";
import type { HealthResponse, Paginated, JobSummary } from "../types/api";

interface TopBarProps {
  onMenuToggle: () => void;
  menuOpen: boolean;
}

export function TopBar({ onMenuToggle, menuOpen }: TopBarProps) {
  const health = usePoll<HealthResponse>("/health", 5000);
  const jobs = usePoll<Paginated<JobSummary>>("/jobs?page=1&page_size=5", 8000);

  const modelReady = health.data?.model.ready ?? false;
  const activeJobs =
    jobs.data?.items.filter((j) => j.status === "queued" || j.status === "processing").length ?? 0;

  return (
    <header className="sticky top-0 z-20 flex flex-wrap items-center gap-3 border-b-[3px] border-ink bg-canvas px-4 py-3 md:px-8">
      <button
        className="nb-btn nb-btn--secondary !p-2 md:hidden"
        onClick={onMenuToggle}
        aria-label={menuOpen ? "Close menu" : "Open menu"}
      >
        {menuOpen ? <X size={18} /> : <Menu size={18} />}
      </button>

      {/* Local inference badge */}
      <span className="nb-tag bg-accent-mint" title="All video processing happens on this machine">
        <Activity size={12} />
        LOCAL INFERENCE · VIDEO STAYS ON THIS MACHINE
      </span>

      <div className="ml-auto flex flex-wrap items-center gap-2">
        {/* Backend status */}
        <span
          className={`nb-tag ${health.error || health.data?.status !== "ok" ? "bg-accent-coral" : "bg-accent-mint"}`}
        >
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              health.error || health.data?.status !== "ok" ? "bg-ink" : "bg-ink"
            }`}
            aria-hidden
          />
          {health.error ? "BACKEND OFFLINE" : `API ${health.data?.status?.toUpperCase() ?? "…"}`}
        </span>

        {/* Model readiness */}
        <span className={`nb-tag ${modelReady ? "bg-accent-mint" : "bg-accent-yellow"}`}>
          <Cpu size={12} />
          {modelReady ? `MODEL READY · ${health.data?.model.filename}` : "MODEL NOT LOADED"}
        </span>

        {/* Processing queue */}
        <span className="nb-tag bg-accent-blue">
          {activeJobs} IN QUEUE
        </span>
      </div>
    </header>
  );
}
