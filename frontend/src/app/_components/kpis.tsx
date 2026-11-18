"use client";
import { KpiStrip, type KpiItem } from "@/components/midday/KpiStrip";
import { useChartSeries, useOverview, usePortfolioKpis } from "@/lib/hooks";
import type { Goal, MV, PortfolioKpi } from "@/lib/types";
import { QueryState } from "./common";

const LABELS: Record<string, string> = {
  gmv: "GMV", creator_attributed_gmv: "Creator-attributed GMV", net_attributed_sales: "Net attributed sales",
  videos: "Videos", active_creators: "Active creators",
};

function basisOf(b: unknown): string | null {
  if (typeof b === "string") return b;
  if (b && typeof b === "object" && "value" in b) {
    const v = (b as MV).value;
    return v === null || v === undefined ? null : String(v);
  }
  return null;
}

/** Portfolio KPI strip. Target/projected/required pace come from the portfolio pacing series meta (API values). */
export function PortfolioKpiStrip() {
  const kpis = usePortfolioKpis();
  const pacing = useChartSeries(null, "pacing_trajectory");
  const meta = pacing.data?.meta;
  return (
    <QueryState q={kpis}>
      {kpis.data && (
        <div className="space-y-2">
          <KpiStrip
            items={kpis.data.kpis.map((k: PortfolioKpi): KpiItem => {
              const paced = k.metric_key === "gmv" && meta;
              return {
                key: k.metric_key,
                label: LABELS[k.metric_key] ?? k.metric_key.replace(/_/g, " "),
                value: k.value,
                progress: k.progress ?? null,
                ...(paced
                  ? { target: meta.target ?? null, projection: meta.projection ?? null, requiredPace: meta.required_pace ?? null, basis: basisOf(meta.basis) }
                  : {}),
              };
            })}
          />
          <div className="flex flex-wrap items-center gap-4 border border-border bg-card px-4 py-2 text-sm text-muted-foreground" aria-label="Pace counts">
            <span>Pace across brands</span>
            <span className="text-emerald-600 dark:text-emerald-400">on track <span className="font-mono tabular-nums">{kpis.data.pace_counts.on_track}</span></span>
            <span className="text-amber-600 dark:text-amber-400">at risk <span className="font-mono tabular-nums">{kpis.data.pace_counts.at_risk}</span></span>
            <span className="text-rose-600 dark:text-rose-400">off track <span className="font-mono tabular-nums">{kpis.data.pace_counts.off_track}</span></span>
            <span>unknown <span className="font-mono tabular-nums">{kpis.data.pace_counts.unknown}</span></span>
          </div>
        </div>
      )}
    </QueryState>
  );
}

export function goalItem(g: Goal): KpiItem {
  return {
    key: g.goal_id, label: g.label, value: g.actual, progress: g.progress ?? null, target: g.target, projection: g.projection,
    requiredPace: g.required_pace, basis: g.basis === "gross" || g.basis === "net" ? g.basis : null, paceStatus: g.pace_status,
  };
}

/** Brand KPI strip from /overview goals. */
export function BrandKpiStrip({ brandId }: { brandId: string }) {
  const ov = useOverview();
  const brand = ov.data?.brands.find((b) => b.brand_id === brandId);
  return (
    <QueryState q={ov}>
      {brand
        ? <KpiStrip items={brand.goals.map(goalItem)} />
        : <p className="text-sm text-muted-foreground">UNAVAILABLE: no goals returned for this brand.</p>}
    </QueryState>
  );
}
