"use client";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { HatchPattern } from "@/components/midday/HatchDefs";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { useEvidenceSheet } from "@/components/midday/EvidenceSheet";
import { HATCH_FILL, POINT_STATUS_LABEL } from "@/lib/chart-theme";
import { useChartSeries } from "@/lib/hooks";
import type { RetainerCadencePoint } from "@/lib/types";
import { formatCount, formatPercent, ChartFrame, AllMissingPlot, LegendItem, hatchAreas, T, MONO, num, type ChartProps } from "./_shared";

const config: ChartConfig = {
  expected: { label: "Expected posts", color: T.expectedPosts },
  actual: { label: "Actual posts", color: T.actualPosts },
};
type Row = { x: string; expected: number | null; actual: number | null; _p: RetainerCadencePoint };

export function RetainerCadenceChart({ brandId, month, cutoff }: ChartProps) {
  const query = useChartSeries(brandId, "retainer_cadence", { month, cutoff });
  const { open } = useEvidenceSheet();

  return (
    <ChartFrame
      title="Retainer cadence"
      description="Expected vs actual posts per retainer creator, trailing complete months."
      query={query}
      info={{
        what: "For each retainer creator, the posts the contract expects against the posts actually published, month by month.",
        how: "Orange bars are expected posts, blue bars are actual posts and the percentage underneath is attainment. A hatched cell means the video data has a gap, so the result is unknown.",
        decision: "Shows which retainer creators are under-delivering and need a nudge or a contract review.",
      }}
      empty="No retainer creators for this selection."
      legend={
        <>
          <LegendItem color={T.expectedPosts} label="Expected" />
          <LegendItem color={T.actualPosts} label="Actual" />
          <LegendItem color="transparent" label="No video data" hatched />
        </>
      }
    >
      {(d) => {
        const groups = new Map<string, RetainerCadencePoint[]>();
        for (const p of d.points) {
          const k = `${p.brand_id ?? ""}|${p.creator_id}`;
          groups.set(k, [...(groups.get(k) ?? []), p]);
        }
        return (
          <div className="grid gap-px border border-border bg-border md:grid-cols-2 xl:grid-cols-3">
            {[...groups.entries()].map(([k, ps]) => {
              const rows: Row[] = ps.map((p) => ({ x: p.x, expected: num(p.expected_posts), actual: num(p.posts), _p: p }));
              const gaps = rows.filter((r) => r.expected === null || r.actual === null);
              return (
                <div key={k} className="bg-card p-3">
                  <div className="mb-1 flex items-baseline justify-between text-xs">
                    <span className="font-medium">{ps[0].handle}</span>
                    {ps[0].brand_id && <span className="text-muted-foreground">{ps[0].brand_id}</span>}
                  </div>
                  {rows.every((r) => r.expected === null && r.actual === null) ? <AllMissingPlot xs={rows.map((r) => r.x)} height={144} note="No video data for these months" /> : (
                  <ChartContainer config={config} className="aspect-auto h-36 w-full">
                    <BarChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                      <CartesianGrid vertical={false} />
                      <XAxis dataKey="x" tickLine={false} axisLine={false} />
                      <YAxis tickLine={false} axisLine={false} width={24} allowDecimals={false} domain={[0, "auto"]} />
                      <ChartTooltip
                        content={
                          <ChartTooltipContent
                            valueFormatter={(_v, key, item) => {
                              const p: RetainerCadencePoint = item.payload._p;
                              return key === "expected" ? formatCount(p.expected_posts) : formatCount(p.posts);
                            }}
                            statusFor={(pl) => {
                              const p: RetainerCadencePoint = pl[0].payload._p;
                              return <>Attainment {formatPercent(p.attainment_pct)}. {POINT_STATUS_LABEL[p.status] ?? p.status}{p.status_reason ? `: ${p.status_reason}` : ""}. Click a bar for evidence.</>;
                            }}
                          />
                        }
                      />
                      <defs><HatchPattern /></defs>
                      {hatchAreas(gaps.map((r) => ({ x: r.x, status: "unavailable" })))}
                      <Bar dataKey="expected" fill="var(--color-expected)" isAnimationActive={false} />
                      <Bar dataKey="actual" fill="var(--color-actual)" isAnimationActive={false} cursor="pointer"
                        onClick={(e: { payload?: Row }) => { const u = e?.payload?._p.evidence_urls?.posts; if (u) open(u, `Posts · ${e.payload!._p.handle} · ${e.payload!._p.x}`); }} />
                    </BarChart>
                  </ChartContainer>
                  )}
                  <div className={`grid border-t border-border pt-1 text-xs ${MONO}`} style={{ gridTemplateColumns: `repeat(${rows.length}, minmax(0, 1fr))` }}>
                    {rows.map((r) => (
                      <div key={r.x} className="text-center">
                        {r._p.attainment_pct === null ? (
                          <span className="text-muted-foreground" title={r._p.status_reason ?? "No video data for this month"}>No data yet<span className="block font-sans text-xs">No video data for this month</span></span>
                        ) : (
                          <span>{formatPercent(r._p.attainment_pct)}</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        );
      }}
    </ChartFrame>
  );
}
