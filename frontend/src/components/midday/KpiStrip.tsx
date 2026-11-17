"use client";
import { formatMV } from "@/lib/format";
import type { MV, PaceStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useEvidenceSheet } from "./EvidenceSheet";
import { GoalBasisBadge, StatusBadge } from "./StatusBadge";

export interface KpiItem {
  key: string;
  label: string;
  /** Headline MetricValue (actual). */
  value: MV | null | undefined;
  target?: MV | null;
  /** API-provided progress ratio MV (actual/target, capped 1.5). The bar is drawn from this only. */
  progress?: MV | null;
  projection?: MV | null;
  requiredPace?: MV | null;
  /** e.g. "gross" | "net". */
  basis?: string | null;
  paceStatus?: PaceStatus;
}
export interface KpiStripProps { items: KpiItem[]; className?: string }

/** Bar width straight from the API `progress` ratio (decimal-point shift of the string; no arithmetic). CSS max-width caps at 100%. */
function barWidth(progress: MV | null | undefined): string | null {
  if (!progress || progress.value === null) return null;
  const m = /^(\d+)(?:\.(\d+))?$/.exec(String(progress.value));
  if (!m) return null;
  const pct = (m[1] + (m[2] ?? "").padEnd(2, "0").slice(0, 2)).replace(/^0+(?=\d)/, "");
  return `${pct}%`;
}

function barColor(item: KpiItem): string {
  if (item.value && item.value.status !== "current") return "bg-amber-500";
  if (item.paceStatus === "off_track") return "bg-rose-500";
  if (item.paceStatus === "at_risk") return "bg-amber-500";
  if (item.paceStatus === "on_track") return "bg-emerald-500";
  return "bg-zinc-500";
}

function NumButton({ mv, label, className }: { mv: MV | null | undefined; label: string; className?: string }) {
  const { open } = useEvidenceSheet();
  if (!mv) return <span className="font-mono text-muted-foreground">UNAVAILABLE</span>;
  return (
    <button type="button" title="Show evidence" onClick={() => open(mv.evidence_url, label)}
      className={cn("font-mono tabular-nums tracking-tight hover:underline", mv.value === null && "text-muted-foreground", className)}>
      {formatMV(mv)}
    </button>
  );
}

function Cell({ item }: { item: KpiItem }) {
  const v = item.value;
  const unknown = !v || v.value === null;
  const w = barWidth(item.progress);
  return (
    <div className="flex min-w-[220px] flex-1 flex-col gap-2 p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">{item.label}</span>
        <GoalBasisBadge basis={item.basis} />
      </div>
      {unknown ? (
        <div className="flex flex-col items-start gap-1">
          <StatusBadge
            status={v && (v.status === "partial" || v.status === "stale") ? "incomplete" : "missing"}
            label={v && (v.status === "partial" || v.status === "stale") ? "INCOMPLETE" : "UNAVAILABLE"}
          />
          {v?.status_reason && <span className="text-xs leading-tight text-muted-foreground">{v.status_reason}</span>}
        </div>
      ) : (
        <div className="flex items-baseline gap-2">
          <NumButton mv={v} label={item.label} className="text-3xl" />
          {v!.status !== "current" && <StatusBadge status={v!.status} />}
        </div>
      )}
      {(item.target !== undefined || item.progress !== undefined) && (
        <div className="space-y-1">
          <div className="h-1.5 w-full bg-muted">
            {w !== null ? <div className={cn("h-full max-w-full", barColor(item))} style={{ width: w }} /> : (
              <svg width="100%" height="6" aria-label="progress unavailable"><rect width="100%" height="6" fill="url(#missing-data-hatch)" /></svg>
            )}
          </div>
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{w === null ? "progress UNAVAILABLE" : "target"}</span>
            <NumButton mv={item.target} label={`${item.label} target`} />
          </div>
        </div>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
        {item.projection !== undefined && (<><dt>Projected</dt><dd className="text-right text-foreground"><NumButton mv={item.projection} label={`${item.label} projected`} /></dd></>)}
        {item.requiredPace !== undefined && (<><dt>Required daily pace</dt><dd className="text-right text-foreground"><NumButton mv={item.requiredPace} label={`${item.label} required pace`} /></dd></>)}
        <dt>Coverage through</dt>
        <dd className="text-right font-mono tabular-nums tracking-tight text-foreground">{v?.coverage_through ?? "UNAVAILABLE"}</dd>
      </dl>
    </div>
  );
}

/** Connected hairline KPI cells. Every number opens the EvidenceSheet. */
export function KpiStrip({ items, className }: KpiStripProps) {
  return (
    <div className={cn("flex flex-wrap divide-x divide-y divide-border border border-border bg-card [&>*]:border-0", className)}>
      {items.map((i) => <Cell key={i.key} item={i} />)}
    </div>
  );
}
