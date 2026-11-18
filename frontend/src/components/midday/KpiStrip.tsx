"use client";
import { formatMV } from "@/lib/format";
import type { MV, PaceStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useEvidenceSheet } from "./EvidenceSheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { GoalBasisBadge, StatusBadge, reasonText } from "./StatusBadge";

export interface KpiItem {
  key: string;
  label: string;
  /** Headline MetricValue (actual). */
  value: MV | null | undefined;
  target?: MV | null;
  /** API-provided progress ratio MV (actual/target, capped 1.5). The bar is drawn from this only. */
  progress?: MV | null;
  projection?: MV | null;
  /** Render the projection as plain text (no evidence click). */
  projectionStatic?: boolean;
  requiredPace?: MV | null;
  /** From the goal's required_pace_applicable. false (or no value) hides the Required daily pace row. */
  requiredPaceApplicable?: boolean;
  /** Goal's required_pace_reason: tooltip text when applicable but the value is null. */
  requiredPaceReason?: string | null;
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

function NoData({ reason }: { reason?: string }) {
  if (!reason) return <span className="text-muted-foreground">No data yet</span>;
  return (
    <Tooltip>
      <TooltipTrigger asChild><span tabIndex={0} className="cursor-help text-muted-foreground underline decoration-dotted">No data yet</span></TooltipTrigger>
      <TooltipContent className="max-w-xs text-sm">{reason}</TooltipContent>
    </Tooltip>
  );
}

function NumButton({ mv, label, className }: { mv: MV | null | undefined; label: string; className?: string }) {
  const { open } = useEvidenceSheet();
  if (!mv || mv.value === null) return <NoData reason={reasonText(mv?.status_reason, mv?.data_note)} />;
  return (
    <button type="button" title="Show evidence" onClick={() => open(mv.evidence_url, label)}
      className={cn("font-mono tabular-nums tracking-tight hover:underline", className)}>
      {formatMV(mv)}
    </button>
  );
}

function Cell({ item }: { item: KpiItem }) {
  const v = item.value;
  const unknown = !v || v.value === null;
  const w = barWidth(item.progress);
  const reason = reasonText(v?.status_reason, v?.data_note);
  const showPace = item.requiredPaceApplicable !== false && item.requiredPace !== undefined && item.requiredPace !== null;
  const paceNull = showPace && item.requiredPace!.value === null;
  return (
    <div className="flex min-w-[220px] flex-1 flex-col gap-2 p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm text-muted-foreground">{item.label}</span>
        <GoalBasisBadge basis={item.basis} />
      </div>
      {unknown ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xl text-muted-foreground">No data yet</span>
          <StatusBadge status={v && v.status === "stale" ? "stale" : "partial"} reason={reason ?? "There is not enough data yet to show this figure."} />
        </div>
      ) : (
        <div className="flex flex-wrap items-baseline gap-2">
          <NumButton mv={v} label={item.label} className="text-3xl" />
          {v!.status !== "current" && <StatusBadge status={v!.status} reason={reason} />}
        </div>
      )}
      {w !== null && (
        <div className="space-y-1">
          <div className="h-1.5 w-full bg-muted">
            <div className={cn("h-full max-w-full", barColor(item))} style={{ width: w }} />
          </div>
          <div className="flex justify-between gap-2 text-sm text-muted-foreground">
            <span>Target</span>
            <NumButton mv={item.target} label={`${item.label} target`} />
          </div>
        </div>
      )}
      {w === null && item.target !== undefined && item.target !== null && (
        <div className="flex justify-between gap-2 text-sm text-muted-foreground">
          <span>Target</span>
          <NumButton mv={item.target} label={`${item.label} target`} />
        </div>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm text-muted-foreground">
        {item.projection !== undefined && (<><dt>Projected</dt><dd className="text-right text-foreground">{item.projectionStatic || !item.projection?.evidence_url
          ? (item.projection && item.projection.value !== null ? <span className="font-mono tabular-nums tracking-tight">{formatMV(item.projection)}</span> : <NoData reason={reasonText(item.projection?.status_reason, item.projection?.data_note)} />)
          : <NumButton mv={item.projection} label={`${item.label} projected`} />}</dd></>)}
        {showPace && (
          <>
            <dt>Required daily pace</dt>
            <dd className="text-right text-foreground">
              {paceNull ? <NoData reason={item.requiredPaceReason ?? reasonText(item.requiredPace!.status_reason)} /> : <NumButton mv={item.requiredPace} label={`${item.label} required pace`} />}
            </dd>
          </>
        )}
        <dt>Data through</dt>
        <dd className="text-right font-mono tabular-nums tracking-tight text-foreground">{v?.coverage_through ?? "No data yet"}</dd>
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
