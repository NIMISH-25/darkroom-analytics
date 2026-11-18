"use client";
import { useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, XAxis, YAxis } from "recharts";
import { HatchPattern } from "@/components/midday/HatchDefs";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useEvidenceSheet } from "@/components/midday/EvidenceSheet";
import { CHART_MARGIN, HATCH_FILL, POINT_STATUS_LABEL } from "@/lib/chart-theme";
import { useChartSeries } from "@/lib/hooks";
import type { DailyGmvPoint } from "@/lib/types";
import { formatMoney, ChartFrame, AllMissingPlot, LegendItem, T, compactTick, hatchAreas, num, type ChartProps } from "./_shared";

const FIELD_LABEL: Record<string, string> = { gmv: "Gross shop sales", creator_attributed_gmv: "Creator-attributed sales", attributed_refunds_cohort: "Refunds (by order date)", attributed_refunds_processed: "Refunds (by refund date)", net_attributed_sales: "Net attributed sales" };
type Basis = "cohort" | "processed";
type Row = { x: string; shop: number | null; gross: number | null; refunds: number | null; net: number | null; _p: DailyGmvPoint };
type Field = "gmv" | "creator_attributed_gmv" | "attributed_refunds_cohort" | "attributed_refunds_processed" | "net_attributed_sales";

export function DailyGmvRefundsChart({ brandId, month, cutoff }: ChartProps) {
  const [basis, setBasis] = useState<Basis>("cohort");
  const query = useChartSeries(brandId, "daily_gmv_refunds", { month, cutoff });
  const { open } = useEvidenceSheet();
  const refundField: Field = basis === "cohort" ? "attributed_refunds_cohort" : "attributed_refunds_processed";
  const config: ChartConfig = {
    shop: { label: "Gross shop GMV", color: T.grossGmv },
    gross: { label: "Creator-attributed GMV", color: T.attributedGmv },
    refunds: { label: basis === "cohort" ? "Refunds (cohort)" : "Refunds (processed)", color: T.refunds },
    net: { label: "Net attributed sales", color: T.netSales },
  };
  const fieldOf: Record<string, Field> = { shop: "gmv", gross: "creator_attributed_gmv", refunds: refundField, net: "net_attributed_sales" };

  return (
    <ChartFrame
      title="Daily attributed GMV vs refunds"
      description="Creator-attributed gross GMV and completed refunds per day, with net attributed sales."
      query={query}
      info={{
        what: "Each day's gross shop GMV, creator-attributed GMV and refunds, plus the net attributed sales line.",
        how: "Blue and green bars are gross and attributed sales, the pink bar is refunds and the purple line is attributed sales after refunds. Hatched days have missing or stale data, not zero.",
        decision: "Shows whether creators are really driving sales or whether refunds are eating the gains.",
      }}
      legend={
        <>
          <LegendItem color={T.grossGmv} label="Gross GMV" />
          <LegendItem color={T.attributedGmv} label="Attributed GMV" />
          <LegendItem color={T.refunds} label="Refunds" />
          <LegendItem color={T.netSales} label="Net attributed (line)" />
          <LegendItem color="transparent" label="Missing / stale" hatched />
        </>
      }
      headerExtra={
        <Tabs value={basis} onValueChange={(v) => setBasis(v as Basis)} className="mb-3">
          <TabsList>
            <TabsTrigger value="cohort">Refunds by order cohort</TabsTrigger>
            <TabsTrigger value="processed">Refunds by processed date</TabsTrigger>
          </TabsList>
        </Tabs>
      }
    >
      {(d) => {
        const rows: Row[] = d.points.map((p) => ({
          x: p.x, shop: num(p.gmv), gross: num(p.creator_attributed_gmv), refunds: num(p[refundField]), net: num(p.net_attributed_sales), _p: p,
        }));
        const openField = (row: Row | undefined, field: Field) => {
          const url = row?._p.evidence_urls?.[field];
          if (url) open(url, `${FIELD_LABEL[field]} · ${row?._p.x}`);
        };
        const hasValues = rows.some((r) => r.gross !== null || r.shop !== null || r.refunds !== null || r.net !== null);
        if (!hasValues) return <AllMissingPlot xs={rows.map((r) => r.x)} note="No data yet for this period" />;
        return (
          <ChartContainer config={config} className="aspect-auto h-72 w-full">
            <ComposedChart data={rows} margin={CHART_MARGIN}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="x" tickLine={false} axisLine={false} tickFormatter={(v: string) => v.slice(5)} minTickGap={16} />
              <YAxis tickLine={false} axisLine={false} width={48} tickFormatter={compactTick} domain={[0, "auto"]} />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    valueFormatter={(_v, key, item) => formatMoney(item.payload._p[fieldOf[key]])}
                    statusFor={(pl) => {
                      const p: DailyGmvPoint = pl[0].payload._p;
                      return <>{POINT_STATUS_LABEL[p.status] ?? p.status}{p.status_reason ? `: ${p.status_reason}` : ""}. Click to open evidence.</>;
                    }}
                  />
                }
              />
              <defs><HatchPattern /></defs>
              {hatchAreas(rows.map((r) => ({ x: r.x, status: r._p.status === "current" && r.gross === null && r.shop === null && r.net === null ? "unavailable" : r._p.status })))}
              <Bar dataKey="shop" fill="var(--color-shop)" isAnimationActive={false} cursor="pointer" onClick={(e: { payload?: Row }) => openField(e?.payload, "gmv")} />
              <Bar dataKey="gross" fill="var(--color-gross)" isAnimationActive={false} cursor="pointer" onClick={(e: { payload?: Row }) => openField(e?.payload, "creator_attributed_gmv")} />
              <Bar dataKey="refunds" fill="var(--color-refunds)" isAnimationActive={false} cursor="pointer" onClick={(e: { payload?: Row }) => openField(e?.payload, refundField)} />
              <Line
                dataKey="net" type="monotone" stroke="var(--color-net)" strokeWidth={2.5} dot={{ r: 3, fill: T.netSales }} connectNulls={false} isAnimationActive={false}
                activeDot={{ r: 4, onClick: ((p: { payload?: Row }) => openField(p?.payload, "net_attributed_sales")) as never }}
              />
            </ComposedChart>
          </ChartContainer>
        );
      }}
    </ChartFrame>
  );
}
