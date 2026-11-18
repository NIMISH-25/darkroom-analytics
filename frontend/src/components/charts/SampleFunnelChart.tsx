"use client";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { useEvidenceSheet } from "@/components/midday/EvidenceSheet";
import { MetricValue } from "@/components/midday/MetricValue";
import { HATCH_FILL, POINT_STATUS_LABEL } from "@/lib/chart-theme";
import { formatCount } from "@/lib/format";
import { useApiQuery, useChartSeries } from "@/lib/hooks";
import type { FunnelLagPoint, Samples } from "@/lib/types";
import { ChartFrame, T, num, type ChartProps } from "./_shared";

const LAGS = ["0-7", "8-14", "15-21", "22-30"];
const config: ChartConfig = { count: { label: "Samples", color: T.statusOk } };

type Pct = { pct_of_sent?: string | null; pct_of_converted?: string | null };
const pctOf = (p?: FunnelLagPoint) => { const x = p as (FunnelLagPoint & Pct) | undefined; const v = x?.pct_of_sent ?? x?.pct_of_converted; return v === undefined || v === null ? null : String(v).endsWith("%") ? String(v) : `${v}%`; };

type Row = { label: string; count: number | null; color: string; _p?: FunnelLagPoint };

function Panel({ title, rows, vertical, onPick }: { title: string; rows: Row[]; vertical?: boolean; onPick: (p?: FunnelLagPoint) => void }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</div>
      <ChartContainer config={config} className="aspect-auto w-full" style={{ height: vertical ? 220 : 40 + rows.length * 30 } as React.CSSProperties}>
        <BarChart data={rows} layout={vertical ? "horizontal" : "vertical"} margin={{ top: 16, right: 40, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={vertical ? false : true} horizontal={vertical ? true : false} />
          {vertical ? (
            <>
              <XAxis dataKey="label" tickLine={false} axisLine={false} />
              <YAxis type="number" tickLine={false} axisLine={false} width={32} allowDecimals={false} />
            </>
          ) : (
            <>
              <XAxis type="number" tickLine={false} axisLine={false} allowDecimals={false} />
              <YAxis type="category" dataKey="label" tickLine={false} axisLine={false} width={80} />
            </>
          )}
          <ChartTooltip
            content={
              <ChartTooltipContent
                valueFormatter={(_v, _k, item) => formatCount(item.payload._p?.count ?? null)}
                statusFor={(pl) => {
                  const p: FunnelLagPoint | undefined = pl[0].payload._p;
                  return <>{pctOf(p) ? `${pctOf(p)} of ${p?.group === "lag" ? "converted" : "sent"}. ` : ""}{p ? POINT_STATUS_LABEL[p.status] ?? p.status : "Missing"}{p?.status_reason ? `: ${p.status_reason}` : ""}. Click for evidence.</>;
                }}
              />
            }
          />
          <Bar dataKey="count" isAnimationActive={false} cursor="pointer" onClick={(e: { payload?: Row }) => onPick(e?.payload?._p)}>
            {rows.map((r, i) => <Cell key={i} fill={r.count === null ? HATCH_FILL : r.color} />)}
            <LabelList dataKey="count" position={vertical ? "top" : "right"} className="fill-foreground font-mono text-xs" content={((p: { x?: number; y?: number; width?: number; height?: number; index?: number; value?: unknown }) => { const r = rows[p.index ?? 0]; const pc = r ? pctOf(r._p) : null; const x = (p.x ?? 0) + (vertical ? (p.width ?? 0) / 2 : (p.width ?? 0) + 4); const y = (p.y ?? 0) + (vertical ? -4 : (p.height ?? 0) / 2 + 4); return <text x={x} y={y} textAnchor={vertical ? "middle" : "start"} className="fill-foreground font-mono text-xs">{p.value === null || p.value === undefined ? "" : String(p.value)}{pc ? ` (${pc})` : ""}</text>; }) as never} />
          </Bar>
        </BarChart>
      </ChartContainer>
    </div>
  );
}

export function SampleFunnelChart({ brandId, month, cutoff }: ChartProps) {
  const query = useChartSeries(brandId, "sample_funnel_lag", { month, cutoff });
  const samples = useApiQuery<Samples>(brandId ? `/api/v1/brands/${brandId}/samples` : null);
  const { open } = useEvidenceSheet();

  return (
    <ChartFrame title="Delivery-to-video lag" description="Days from delivery to the first video, for converted samples. Hatched bars are unknown, not zero." query={query} info={{
      what: "How many days creators take to post a video after a sample is delivered.",
      how: "Each bar counts converted samples in a time window, with its share of converted samples beside it. A hatched bar means the count is unknown, not zero.",
      decision: "Tells you how long to wait before chasing a creator, and whether sampling turns into content quickly enough.",
    }}>
      {(d) => {
        const lag = new Map(d.points.filter((p) => p.group === "lag").map((p) => [p.x, p]));
        const lagRows: Row[] = LAGS.map((k) => ({ label: `${k} d`, color: T.statusOk, count: num(lag.get(k)?.count), _p: lag.get(k) }));
        const pick = (p?: FunnelLagPoint) => {
          const url = p?.evidence_urls?.count;
          if (url) open(url, `Samples: ${p?.x}`);
        };
        return (
          <>
            {samples.data && (
              <div className="text-xs text-muted-foreground">Conversion rate: <MetricValue mv={samples.data.counts.conversion_rate} label="Sample conversion rate" /></div>
            )}
            <div className="grid gap-6">
                            <Panel title="Delivery to video lag (converted samples)" rows={lagRows} vertical onPick={pick} />
            </div>
          </>
        );
      }}
    </ChartFrame>
  );
}
