"use client";
import { CartesianGrid, ReferenceDot, ReferenceLine, Scatter, ScatterChart, XAxis, YAxis, ZAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { MetricValue } from "@/components/midday/MetricValue";
import { useEvidenceSheet } from "@/components/midday/EvidenceSheet";
import { POINT_STATUS_LABEL, SERIES_COLORS } from "@/lib/chart-theme";
import { formatMoney } from "@/lib/format";
import { useChartSeries } from "@/lib/hooks";
import type { ConcentrationPoint } from "@/lib/types";
import { ChartFrame, LegendItem, T, MONO, num, type ChartProps } from "./_shared";

type Row = { x: number; y: number; _p: ConcentrationPoint };

const pctText = (v: unknown): string => (v === null || v === undefined ? "UNAVAILABLE" : String(v).endsWith("%") ? String(v) : `${v}%`);
const pctNum = (v: unknown): number | null => {
  const n = v === null || v === undefined ? null : Number(String(v).replace("%", ""));
  return n === null || !Number.isFinite(n) ? null : n;
};

export function CreatorConcentrationChart({ brandId, month, cutoff }: ChartProps) {
  const query = useChartSeries(brandId, "creator_concentration", { month, cutoff });
  const { open } = useEvidenceSheet();

  return (
    <ChartFrame
      title="Creator concentration"
      description="Cumulative GMV share vs cumulative creator share (creators ranked by gross GMV). Dashed line = perfect equality."
      query={query}
      info={{
        what: "How much of the creator-attributed GMV comes from your biggest creators.",
        how: "The solid curve climbs fast when a few creators dominate and the dotted diagonal is a perfectly even spread. Dots mark the share held by the top 10% and 20% of creators.",
        decision: "Shows how exposed the brand is if one or two creators leave, and whether to diversify.",
      }}
    >
      {(d) => {
        const groups = new Map<string, ConcentrationPoint[]>();
        for (const p of d.points) {
          const k = p.brand_id ?? "brand";
          groups.set(k, [...(groups.get(k) ?? []), p]);
        }
        const keys = [...groups.keys()];
        const config: ChartConfig = Object.fromEntries(keys.map((k, i) => [k, { label: k, color: SERIES_COLORS[i % SERIES_COLORS.length] }]));
        const toRows = (ps: ConcentrationPoint[]): Row[] =>
          ps.flatMap((p) => {
            const x = num(p.cum_creator_pct), y = num(p.cum_gmv_pct);
            return x === null || y === null ? [] : [{ x, y, _p: p }];
          });
        const someUnavailable = d.points.some((p) => num(p.cum_creator_pct) === null || num(p.cum_gmv_pct) === null);
        const m = d.meta as Record<string, unknown>;
        const marks = [
          { label: "Top 10% of creators", x: 10, raw: m.top10_gmv_share },
          { label: "Top 20% of creators", x: 20, raw: m.top20_gmv_share },
        ].filter((k) => "top10_gmv_share" in m || "top20_gmv_share" in m);
        const pick = (e: { payload?: Row } | undefined) => {
          const p = e?.payload?._p;
          const url = p?.evidence_urls?.gmv;
          if (p && url) open(url, `GMV · ${p.handle}`);
        };
        return (
          <>
            <ChartContainer config={config} className="aspect-auto h-72 w-full">
              <ScatterChart margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                <CartesianGrid />
                <XAxis type="number" dataKey="x" domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(v: number) => `${v}%`} tickLine={false} axisLine={false} name="Creators" />
                <YAxis type="number" dataKey="y" domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(v: number) => `${v}%`} tickLine={false} axisLine={false} width={44} name="GMV" />
                <ZAxis range={[36, 36]} />
                <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]} stroke={T.target} strokeWidth={2.5} strokeDasharray="2 4" ifOverflow="visible" />
                <ChartTooltip
                  cursor={false}
                  content={
                    <ChartTooltipContent
                      labelFormatter={(_l, pl) => {
                        const p: ConcentrationPoint | undefined = pl[0]?.payload?._p;
                        return p ? `${p.handle}${p.brand_id ? ` (${p.brand_id})` : ""} · rank ${p.x}` : "";
                      }}
                      valueFormatter={(_v, key, item) => {
                        const p: ConcentrationPoint = item.payload._p;
                        return pctText(key === "x" ? p.cum_creator_pct : p.cum_gmv_pct);
                      }}
                      statusFor={(pl) => {
                        const p: ConcentrationPoint = pl[0].payload._p;
                        return <>GMV {formatMoney(p.gmv)} · share {pctText((p as { share_pct?: string | null }).share_pct ?? null)}. {POINT_STATUS_LABEL[p.status] ?? p.status}. Click for evidence.</>;
                      }}
                    />
                  }
                />
                {marks.map((k) => {
                  const y = pctNum(k.raw);
                  return y === null ? null : <ReferenceDot key={k.label} x={k.x} y={y} r={6} fill={T.statusWarn} stroke="hsl(var(--background))" strokeWidth={2} ifOverflow="visible" />;
                })}
                {keys.map((k) => (
                  <Scatter key={k} name={k} data={toRows(groups.get(k)!)} fill={`var(--color-${k})`} line={{ stroke: `var(--color-${k})`, strokeWidth: 2.5 }} isAnimationActive={false} cursor="pointer" onClick={pick}
                  />
                ))}
              </ScatterChart>
            </ChartContainer>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground">
              {keys.length > 1 && keys.map((k, i) => <LegendItem key={k} color={SERIES_COLORS[i % SERIES_COLORS.length]} label={k} />)}
              {marks.map((k) => (
                <span key={k.label} className={MONO}>{k.label}: {pctText(k.raw)} of GMV</span>
              ))}
              {someUnavailable && <span>Some points are UNAVAILABLE (not plotted).</span>}
              {d.meta.unresolved_gmv && <span>Unresolved GMV (not in any creator): <MetricValue mv={d.meta.unresolved_gmv} /></span>}
            </div>
          </>
        );
      }}
    </ChartFrame>
  );
}
