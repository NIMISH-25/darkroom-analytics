"use client";
import { formatMV, UNAVAILABLE } from "@/lib/format";
import type { MV } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useEvidenceSheet } from "./EvidenceSheet";
import { StatusBadge } from "./StatusBadge";

export interface MetricValueProps {
  mv: MV | null | undefined;
  /** Title for the evidence sheet. */
  label?: string;
  /** Show the freshness badge (default: only when status is not current). */
  showBadge?: "always" | "auto" | "never";
  /** Show status_reason under a null value (default true). */
  showReason?: boolean;
  className?: string;
}

/** Any MetricValue in a table/cell: mono value (UNAVAILABLE when null, never 0), freshness badge, click opens EvidenceSheet. */
export function MetricValue({ mv, label, showBadge = "auto", showReason = true, className }: MetricValueProps) {
  const { open } = useEvidenceSheet();
  if (!mv) return <span className="font-mono text-muted-foreground">{UNAVAILABLE}</span>;
  const unknown = mv.value === null;
  const badge = showBadge === "always" || (showBadge === "auto" && mv.status !== "current");
  return (
    <span className={cn("inline-flex flex-col items-start gap-0.5", className)}>
      <span className="inline-flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => open(mv.evidence_url, label ?? mv.metric_key)}
          className={cn("font-mono tabular-nums tracking-tight underline decoration-dotted underline-offset-2 hover:decoration-solid", unknown && "text-muted-foreground")}
          title="Show evidence"
        >
          {formatMV(mv)}
        </button>
        {badge && <StatusBadge status={mv.status} title={mv.coverage_through ? `coverage through ${mv.coverage_through}` : undefined} />}
      </span>
      {unknown && showReason && mv.status_reason && <span className="max-w-[28ch] text-xs leading-tight text-muted-foreground">{mv.status_reason}</span>}
    </span>
  );
}
