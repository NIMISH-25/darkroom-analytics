"use client";
import { KpiStrip, type KpiItem } from "@/components/midday/KpiStrip";
import { useChartSeries, useOverview, usePortfolioKpis } from "@/lib/hooks";
import type { Goal, MV, PortfolioKpi } from "@/lib/types";
import { QueryState } from "./common";
import type { PortfolioKpisExt } from "./ext";
import { BrandPaceWidget } from "./pace";

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
  const ext = (kpis.data ?? {}) as PortfolioKpisExt;
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
                  ? { projectionStatic: true, target: meta.target ?? null, projection: meta.projection ?? null, requiredPace: meta.required_pace ?? null, basis: basisOf(meta.basis) }
                  : {}),
              };
            })}
          />
          {ext.brand_pace_counts && <BrandPaceWidget counts={ext.brand_pace_counts} brands={ext.brand_pace ?? []} />}
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
        : <p className="text-sm text-muted-foreground">No goals have been set for this brand yet.</p>}
    </QueryState>
  );
}
