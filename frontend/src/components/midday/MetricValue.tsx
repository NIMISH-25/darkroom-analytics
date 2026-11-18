"use client";
import { formatMV, UNAVAILABLE } from "@/lib/format";
import type { MV } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useEvidenceSheet } from "./EvidenceSheet";
import { StatusBadge, reasonText } from "./StatusBadge";

export interface MetricValueProps {
  mv: MV | null | undefined;
  /** Title for the evidence sheet. */
  label?: string;
  /** Show the freshness badge (default: only when status is not current). */
  showBadge?: "always" | "auto" | "never";
  /** Deprecated: reasons now live in the badge tooltip. */
  showReason?: boolean;
  className?: string;
}

/** Any MetricValue in a table/cell: mono value ("No data yet" when null, never 0), freshness badge, click opens EvidenceSheet. */
export function MetricValue({ mv, label, showBadge = "auto", className }: MetricValueProps) {
  const { open } = useEvidenceSheet();
  if (!mv) return <span className="font-mono text-muted-foreground">{UNAVAILABLE}</span>;
  const unknown = mv.value === null;
  const badge = showBadge === "always" || (showBadge === "auto" && (mv.status !== "current" || unknown));
  const reason = reasonText(mv.status_reason, mv.data_note);
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
        {badge && <StatusBadge status={mv.status} reason={reason} />}
      </span>
    </span>
  );
}
