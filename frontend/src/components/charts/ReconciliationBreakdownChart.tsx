"use client";
import { Bar, BarChart, Cell, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { useEvidenceSheet } from "@/components/midday/EvidenceSheet";
import { StatusBadge } from "@/components/midday/StatusBadge";
import { MetricValue } from "@/components/midday/MetricValue";
import { HATCH_FILL, POINT_STATUS_LABEL } from "@/lib/chart-theme";
import { useChartSeries } from "@/lib/hooks";
import type { ReconciliationPoint } from "@/lib/types";
import { formatCount, formatMoney, formatPercent, ChartFrame, MONO, T, Swatch, num, type ChartProps } from "./_shared";

const BUCKETS: { key: ReconciliationPoint["x"]; label: string; color: string }[] = [
  { key: "resolved", label: "Resolved to creator", color: T.attributedGmv },
  { key: "creator_unresolved", label: "Creator unresolved", color: T.grossGmv },
  { key: "none", label: "Unattributed (none)", color: T.statusWarn },
  { key: "conflict", label: "Conflict", color: T.statusError },
];

export function ReconciliationBreakdownChart({ brandId, month, cutoff }: ChartProps) {
  const query = useChartSeries(brandId, "attribution_reconciliation", { month, cutoff });
  const { open } = useEvidenceSheet();

  return (
    <ChartFrame title="Attribution reconciliation" description="Eligible shop GMV by attribution bucket. Buckets sum to total GMV (as returned by the API)." query={query} info={{
      what: "How this period's shop GMV splits by how well each order could be tied to a creator.",
      how: "One bar split into segments: resolved to a creator, creator unresolved, unattributed, and conflicting. A hatched segment means the amount is unknown.",
      decision: "Shows how much revenue you can credit to creators, and whether fixing tracking links would recover more.",
    }}>
      {(d) => {
        const by = new Map(d.points.map((p) => [p.x, p]));
        const row: Record<string, unknown> = { name: "GMV" };
        for (const b of BUCKETS) row[b.key] = num(by.get(b.key)?.amount);
        const config: ChartConfig = Object.fromEntries(BUCKETS.map((b) => [b.key, { label: b.label, color: b.color }]));
        const openBucket = (k: string) => {
          const p = by.get(k as ReconciliationPoint["x"]);
          const url = p?.evidence_urls?.amount ?? Object.values(p?.evidence_urls ?? {})[0];
          if (url) open(url, `Attribution: ${BUCKETS.find((b) => b.key === k)?.label ?? "Other"}`);
        };
        return (
          <>
            <ChartContainer config={config} className="aspect-auto h-20 w-full">
              <BarChart data={[row]} layout="vertical" margin={{ top: 4, right: 4, bottom: 4, left: 4 }} stackOffset="none">
                <XAxis type="number" hide domain={[0, "dataMax"]} />
                <YAxis type="category" dataKey="name" hide />
                <ChartTooltip
                  content={
                    <ChartTooltipContent
                      hideLabel
                      valueFormatter={(_v, key) => {
                        const p = by.get(key as ReconciliationPoint["x"]);
                        return `${formatMoney(p?.amount ?? null)} · ${formatPercent(p?.pct ?? null)}`;
                      }}
                      statusFor={(pl) => {
                        const p = by.get(String(pl[0]?.dataKey) as ReconciliationPoint["x"]);
                        return <>{p ? POINT_STATUS_LABEL[p.status] ?? p.status : "Missing"}{p?.status_reason ? `: ${p.status_reason}` : ""}. Click to open evidence.</>;
                      }}
                    />
                  }
                />
                {BUCKETS.map((b) => (
                  <Bar key={b.key} dataKey={b.key} stackId="s" fill={`var(--color-${b.key})`} isAnimationActive={false} cursor="pointer" onClick={() => openBucket(b.key)}>
                    <Cell fill={row[b.key] === null ? HATCH_FILL : `var(--color-${b.key})`} />
                  </Bar>
                ))}
              </BarChart>
            </ChartContainer>
            <table className={`w-full border-t border-border text-xs ${MONO}`}>
              <thead>
                <tr className="text-left text-muted-foreground font-sans">
                  <th className="py-1.5 font-normal">Bucket</th>
                  <th className="py-1.5 text-right font-normal">Amount</th>
                  <th className="py-1.5 text-right font-normal">Order items</th>
                  <th className="py-1.5 text-right font-normal">Share</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {BUCKETS.map((b) => {
                  const p = by.get(b.key);
                  return (
                    <tr key={b.key} className="cursor-pointer hover:bg-muted/40" onClick={() => openBucket(b.key)}>
                      <td className="py-1.5 font-sans"><span className="inline-flex items-center gap-2"><Swatch color={b.color} hatched={!p || p.amount === null} />{b.label}
                        {p && p.status !== "current" && <StatusBadge status={p.status} />}</span></td>
                      <td className="py-1.5 text-right">{formatMoney(p?.amount ?? null)}</td>
                      <td className="py-1.5 text-right">{formatCount(p?.order_items ?? null)}</td>
                      <td className="py-1.5 text-right">{formatPercent(p?.pct ?? null)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {d.meta.unresolved_gmv && <div className="text-xs text-muted-foreground">Unresolved GMV: <MetricValue mv={d.meta.unresolved_gmv} /></div>}
          </>
        );
      }}
    </ChartFrame>
  );
}
