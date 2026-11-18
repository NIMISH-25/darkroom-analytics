"use client";
import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, XAxis, YAxis } from "recharts";
import { HatchPattern } from "@/components/midday/HatchDefs";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useEvidenceSheet } from "@/components/midday/EvidenceSheet";
import { CHART_MARGIN, HATCH_FILL, POINT_STATUS_LABEL } from "@/lib/chart-theme";
import { useChartSeries } from "@/lib/hooks";
import type { ChartMetric, PacingPoint } from "@/lib/types";
import { formatMV, formatValue, ChartFrame, AllMissingPlot, LegendItem, T, compactTick, hatchAreas, num, type ChartProps } from "./_shared";

const METRICS: { key: ChartMetric; label: string }[] = [
  { key: "gmv", label: "Sales GMV" },
  { key: "videos", label: "Videos Posted" },
  { key: "active_creators", label: "Active Creators" },
];

const config: ChartConfig = {
  actual: { label: "Actual", color: T.actual },
  projection: { label: "Projected", color: T.projection },
  required: { label: "Required pace", color: T.statusWarn },
};

type Row = { x: string; actual: number | null; projection: number | null; required: number | null; _p: PacingPoint };
type DotClick = (p: { payload?: Row }) => void;

export function PacingTrajectoryChart({ brandId, month, cutoff }: ChartProps) {
  const [metric, setMetric] = useState<ChartMetric>("gmv");
  const query = useChartSeries(brandId, "pacing_trajectory", { month, cutoff, metric });
  const { open } = useEvidenceSheet();

  return (
    <ChartFrame
      title="Pacing trajectory"
      description="Cumulative actuals to the cutoff, dashed projection after it. Hatched = unknown, not zero."
      query={query}
      info={{
        what: "Cumulative progress toward this month's goal, day by day, with a projected finish.",
        how: "The solid line is what actually happened up to the cutoff, the dashed line is the projection and the dotted line is the target. Hatched stretches mean data is missing or stale, not zero.",
        decision: "Tells you whether to push creators harder now or accept the month will land short of target.",
      }}
      legend={
        <>
          <LegendItem color={T.actual} label="Actual (solid)" />
          <LegendItem color={T.projection} label="Projected (dashed)" />
          <LegendItem color={T.target} label="Target (dotted)" />
          <LegendItem color={T.statusWarn} label="Required pace" />
          <LegendItem color="transparent" label="Missing / stale" hatched />
        </>
      }
      headerExtra={
        <Tabs value={metric} onValueChange={(v) => setMetric(v as ChartMetric)} className="mb-3">
          <TabsList>
            {METRICS.map((m) => <TabsTrigger key={m.key} value={m.key}>{m.label}</TabsTrigger>)}
          </TabsList>
        </Tabs>
      }
    >
      {(d) => {
        const unit = d.units?.actual ?? (metric === "gmv" ? "USD" : "count");
        const rows: Row[] = d.points.map((p) => ({ x: p.x, actual: num(p.actual), projection: num(p.projection), required: num(p.required), _p: p }));
        const target = d.meta.target ?? null;
        const targetNum = target ? num(target.value) : null;
        const openFor = (row: Row | undefined, field: "actual" | "projection" | "required") => {
          const url = row?._p.evidence_urls?.[field] ?? row?._p.evidence_urls?.actual;
          if (url) open(url, `${METRICS.find((m) => m.key === metric)?.label} · ${row?._p.x}`);
        };
        const dot = (field: "actual" | "projection" | "required") => ({ r: 4, onClick: ((p: { payload?: Row }) => openFor(p?.payload, field)) as DotClick as never });
        const partialPt = rows.map((r) => r._p).find((p) => p.status === "partial" && ((p as { data_note?: string | null }).data_note || p.status_reason));
        const partialNote = partialPt ? ((partialPt as { data_note?: string | null }).data_note ?? partialPt.status_reason) : null;
        const hasValues =rows.some((r) => r.actual !== null || r.projection !== null || r.required !== null);
        return (
          <>
            {partialNote && <p className="mb-2 text-sm text-muted-foreground">{partialNote}</p>}
            {!hasValues ? <AllMissingPlot xs={rows.map((r) => r.x)} note="No data yet for this period" /> : (
            <ChartContainer config={config} className="aspect-auto h-72 w-full">
              <ComposedChart data={rows} margin={CHART_MARGIN}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="x" tickLine={false} axisLine={false} tickFormatter={(v: string) => v.slice(5)} minTickGap={16} />
                <YAxis tickLine={false} axisLine={false} width={48} tickFormatter={compactTick} domain={[0, "auto"]} />
                <ChartTooltip
                  content={
                    <ChartTooltipContent
                      valueFormatter={(_v, key, item) => formatValue(item.payload._p[key], unit)}
                      statusFor={(pl) => {
                        const p: PacingPoint = pl[0].payload._p;
                        return <>{POINT_STATUS_LABEL[p.status] ?? p.status}{p.status_reason ? `: ${p.status_reason}` : ""}. Click a point for evidence.</>;
                      }}
                    />
                  }
                />
                <defs><HatchPattern /></defs>
                {hatchAreas(rows.map((r) => ({ x: r.x, status: r._p.status === "partial" ? "current" : r._p.status === "current" && r.actual === null && r.projection === null && r.required === null ? "unavailable" : r._p.status })))}
                {targetNum !== null && (
                  <ReferenceLine y={targetNum} stroke={T.target} strokeWidth={2.5} strokeDasharray="2 4" ifOverflow="visible" label={{ value: `Target ${formatMV(target)}`, position: "insideTopLeft", fontSize: 12 }} />
                )}
                <Area dataKey="actual" type="monotone" stroke="var(--color-actual)" fill="var(--color-actual)" fillOpacity={0.25} strokeWidth={2.5} connectNulls={false} isAnimationActive={false} dot={{ r: 3, fill: T.actual }} activeDot={dot("actual")} />
                <Line dataKey="projection" type="monotone" stroke="var(--color-projection)" strokeWidth={2.5} strokeDasharray="6 4" dot={false} connectNulls={false} isAnimationActive={false} activeDot={dot("projection")} />
                <Line dataKey="required" type="monotone" stroke="var(--color-required)" strokeWidth={2.5} strokeDasharray="1 4" dot={false} connectNulls={false} isAnimationActive={false} activeDot={dot("required")} />
              </ComposedChart>
            </ChartContainer>
            )}
            <div className="flex flex-wrap gap-x-6 gap-y-1 border-t border-border pt-2 text-xs text-muted-foreground">
              {typeof d.meta.basis === "string" && <span>basis: <span className="font-mono">{d.meta.basis}</span></span>}
              <span>target: <span className="font-mono tabular-nums">{formatMV(target)}</span></span>
              <span>projection: <span className="font-mono tabular-nums">{formatMV(d.meta.projection ?? null)}</span></span>
              <span>required pace: <span className="font-mono tabular-nums">{formatMV(d.meta.required_pace ?? null)}</span></span>
            </div>
          </>
        );
      }}
    </ChartFrame>
  );
}
