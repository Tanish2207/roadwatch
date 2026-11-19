import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  description: string;
  action?: ReactNode;
  icon?: string;
}

export function EmptyState({ title, description, action, icon = "◎" }: EmptyStateProps) {
  return (
    <div className="nb-card flex flex-col items-center gap-3 px-6 py-10 text-center">
      <span
        aria-hidden
        className="font-display text-5xl text-ink/30"
      >
        {icon}
      </span>
      <h3 className="font-display text-lg font-bold uppercase">{title}</h3>
      <p className="max-w-md text-sm text-ink/70">{description}</p>
      {action}
    </div>
  );
}
