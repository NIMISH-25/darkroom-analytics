"use client";
import { useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartCard } from "@/components/midday/ChartCard";
import { StatusBadge } from "@/components/midday/StatusBadge";
import { useEvidenceSheet } from "@/components/midday/EvidenceSheet";
import { apiGet } from "@/lib/api";
import { useMeta } from "@/lib/hooks";
import type { CreatorItem, Creators, MV } from "@/lib/types";
import { MONO, compactTick, formatMV, formatMoney, num, useIsDark, type ChartProps } from "./_shared";

const N = 5;
type Item = CreatorItem & { brand_id: string };
type Row = {
  label: string; net: number | null; retainer: number | null; commission: number | null; sample: number | null; _i: Item;
};

/** Vibrant fills with at least 4.5:1 against the dark canvas (#0C0C0C); the light theme keeps the shared tokens. */
const DARK = { net: "#34D399", retainer: "#60A5FA", commission: "#22D3EE", sample: "#F472B6" };
const LIGHT = { net: "#8B5CF6", retainer: "#0072B2", commission: "#009E73", sample: "#B5578F" };

const costKnown = (i: CreatorItem) => i.retainer_cost.value !== null && i.commission_cost.value !== null && i.sample_cost.value !== null;
const DEFAULT_REASON = "Retainer or rate terms are not on file for this creator";

/** The creator's own plain reason, from the first figure that is missing. */
function ownReason(i: CreatorItem): string | null {
  for (const mv of [i.net_sales, i.retainer_cost, i.commission_cost, i.sample_cost] as (MV & { data_note?: string | null })[]) {
    if (mv.value === null) return mv.data_note ?? mv.status_reason ?? null;
  }
  return null;
}

export function CreatorEconomicsChart({ brandId }: ChartProps) {
  const dark = useIsDark();
  const col = dark ? DARK : LIGHT;
  const meta = useMeta();
  const revision = meta.data?.data_revision;
  const brandIds = brandId ? [brandId] : (meta.data?.brands.map((b) => b.brand_id) ?? []);
  const results = useQueries({
    queries: brandIds.map((id) => {
      const path = `/api/v1/brands/${id}/creators?sort=net_sales&order=desc`;
      return { queryKey: ["api", path, revision], queryFn: () => apiGet<Creators>(path), enabled: revision !== undefined, staleTime: Infinity };
    }),
  });
  const loading = meta.isLoading || results.some((r) => r.isLoading);
  const error = results.find((r) => r.error)?.error;
  const items: Item[] = useMemo(
    () => results.flatMap((r, k) => (r.data?.items ?? []).map((i) => ({ ...i, brand_id: brandIds[k] }))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [results.map((r) => r.dataUpdatedAt).join(","), brandIds.join(",")],
  );
  const { open } = useEvidenceSheet();
  const [hover, setHover] = useState<string | null>(null); // "panel:index"

  const plottable = items.filter((i) => i.net_sales.value !== null && costKnown(i));
  if (!brandId) plottable.sort((a, b) => Number(b.net_sales.value) - Number(a.net_sales.value)); // ordering only
  const unknown = items.filter((i) => !(i.net_sales.value !== null && costKnown(i)));
  const top = plottable.slice(0, N);
  const bottom = plottable.length > N ? plottable.slice(Math.max(N, plottable.length - N)) : [];

  const reasons = unknown.map(ownReason);
  const allSame = reasons.length > 1 && reasons.every((r) => r === reasons[0]);
  const reasonFor = (k: number) => (allSame || !reasons[k] ? DEFAULT_REASON : (reasons[k] as string));

  const config: ChartConfig = {
    net: { label: "Net attributed sales", color: col.net },
    retainer: { label: "Retainer", color: col.retainer },
    commission: { label: "Commission", color: col.commission },
    sample: { label: "Sample cost", color: col.sample },
  };

  const toRow = (i: Item): Row => ({
    label: brandId ? i.handle : `${i.handle} (${i.brand_id})`,
    net: num(i.net_sales.value), retainer: num(i.retainer_cost.value), commission: num(i.commission_cost.value), sample: num(i.sample_cost.value), _i: i,
  });

  const panel = (id: string, title: string, list: Item[]) => {
    const bar = (key: "net" | "retainer" | "commission" | "sample", stackId: string, mvOf: (i: Item) => MV, what: string) => (
      <Bar
        dataKey={key} stackId={stackId} fill={col[key]} isAnimationActive={false} cursor="pointer"
        onMouseEnter={(_d: unknown, idx: number) => setHover(`${id}:${idx}`)} onMouseLeave={() => setHover(null)}
        onClick={(e: { payload?: Row }) => e?.payload && open(mvOf(e.payload._i).evidence_url, `${what} · ${e.payload._i.handle}`)}
      >
        {list.map((_, idx) => (
          <Cell key={idx} fill={col[key]} fillOpacity={hover && hover.startsWith(`${id}:`) && hover !== `${id}:${idx}` ? 0.35 : 1} />
        ))}
      </Bar>
    );
    return (
      <div>
        <div className="mb-1 text-xs font-medium uppercase tracking-wide text-foreground">{title}</div>
        <ChartContainer
          config={config}
          className="aspect-auto w-full [&_.recharts-cartesian-axis-tick_text]:fill-foreground"
          style={{ height: 40 + list.length * 44 } as React.CSSProperties}
        >
          <BarChart data={list.map(toRow)} layout="vertical" margin={{ top: 4, right: 12, bottom: 0, left: 0 }} barCategoryGap={8}>
            <CartesianGrid horizontal={false} />
            <XAxis type="number" tickLine={false} axisLine={false} tickFormatter={compactTick} tick={{ fontSize: 12 }} />
            <YAxis type="category" dataKey="label" tickLine={false} axisLine={false} width={120} tick={{ fontSize: 12 }} />
            <ChartTooltip
              cursor={{ fill: "hsl(var(--muted) / 0.4)" }}
              content={
                <ChartTooltipContent
                  valueFormatter={(_v, key, item) => {
                    const i: Item = item.payload._i;
                    return formatMV({ net: i.net_sales, retainer: i.retainer_cost, commission: i.commission_cost, sample: i.sample_cost }[key as "net"]);
                  }}
                  statusFor={(pl) => <>Contract: {String(pl[0].payload._i.contract_type).replace(/_/g, " ")}. Click a bar for evidence.</>}
                />
              }
            />
            {bar("net", "net", (i) => i.net_sales, "Net sales")}
            {bar("retainer", "cost", (i) => i.retainer_cost, "Retainer")}
            {bar("commission", "cost", (i) => i.commission_cost, "Commission")}
            {bar("sample", "cost", (i) => i.sample_cost, "Sample cost")}
          </BarChart>
        </ChartContainer>
      </div>
    );
  };

  const legendItems = [
    { c: col.net, l: "Net sales" }, { c: col.retainer, l: "Retainer" }, { c: col.commission, l: "Commission" }, { c: col.sample, l: "Sample cost" },
  ];

  return (
    <ChartCard
      title="Creator economics"
      description="Net attributed sales vs known program costs, top and bottom creators by net sales."
      info={{
        what: "Each top and bottom creator's net attributed sales next to the known cost of working with them.",
        how: "The first bar is net sales and the stacked bar beside it is retainer, commission and sample cost. Creators with an unknown cost are listed separately, never drawn as zero.",
        decision: "Helps you decide who to rebook, renegotiate with or drop.",
      }}
    >
      {loading ? <Skeleton className="h-64 w-full" /> : error ? (
        <p className="text-xs text-rose-500">Creator figures could not be loaded right now. Please try again.</p>
      ) : items.length === 0 ? (
        <p className="py-10 text-center text-xs text-muted-foreground">No creators for this selection.</p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-foreground">
            {legendItems.map((x) => (
              <span key={x.l} className="inline-flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5" style={{ background: x.c }} />{x.l}</span>
            ))}
          </div>
          {top.length > 0 ? panel("top", "Top by net sales", top) : <p className="text-xs text-muted-foreground">No creator has both net sales and all costs on file yet.</p>}
          {bottom.length > 0 && panel("bottom", "Bottom by net sales", bottom)}
          <div className="border-t border-border pt-3">
            <div className="mb-1.5 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-foreground">
              Cost unknown <StatusBadge status="unknown" label={`${unknown.length}`} />
            </div>
            {unknown.length === 0 ? <p className="text-xs text-muted-foreground">None</p> : (
              <ul className="divide-y divide-border border border-border text-xs">
                {unknown.map((i, k) => (
                  <li key={`${i.brand_id}-${i.creator_id}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-2 py-1.5">
                    <span className="font-medium">{i.handle}{!brandId && <span className="text-muted-foreground"> ({i.brand_id})</span>}</span>
                    {i.net_sales.value !== null && <span className={`${MONO} text-muted-foreground`}>net sales {formatMoney(i.net_sales.value)}</span>}
                    <span className="text-muted-foreground">{reasonFor(k)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </ChartCard>
  );
}
