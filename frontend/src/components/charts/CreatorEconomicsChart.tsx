"use client";
import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartCard } from "@/components/midday/ChartCard";
import { StatusBadge } from "@/components/midday/StatusBadge";
import { useEvidenceSheet } from "@/components/midday/EvidenceSheet";
import { apiGet } from "@/lib/api";
import { formatMV, formatMoney, UNAVAILABLE } from "@/lib/format";
import { useMeta } from "@/lib/hooks";
import type { CreatorItem, Creators } from "@/lib/types";
import { MONO, LegendItem, T, compactTick, num, type ChartProps } from "./_shared";

const N = 5;
type Item = CreatorItem & { brand_id: string };
type Row = {
  label: string; net: number | null; retainer: number | null; commission: number | null; sample: number | null; _i: Item;
};

const config: ChartConfig = {
  net: { label: "Net attributed sales", color: T.netSales },
  retainer: { label: "Retainer", color: T.grossGmv },
  commission: { label: "Commission", color: T.attributedGmv },
  sample: { label: "Sample cost", color: T.refunds },
};

const costKnown = (i: CreatorItem) => i.retainer_cost.value !== null && i.commission_cost.value !== null && i.sample_cost.value !== null;

export function CreatorEconomicsChart({ brandId }: ChartProps) {
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

  const plottable = items.filter((i) => i.net_sales.value !== null && costKnown(i));
  if (!brandId) plottable.sort((a, b) => Number(b.net_sales.value) - Number(a.net_sales.value)); // ordering only
  const unknown = items.filter((i) => !(i.net_sales.value !== null && costKnown(i)));
  const top = plottable.slice(0, N);
  const bottom = plottable.length > N ? plottable.slice(Math.max(N, plottable.length - N)) : [];

  const toRow = (i: Item): Row => ({
    label: brandId ? i.handle : `${i.handle} (${i.brand_id})`,
    net: num(i.net_sales.value), retainer: num(i.retainer_cost.value), commission: num(i.commission_cost.value), sample: num(i.sample_cost.value), _i: i,
  });

  const panel = (title: string, list: Item[]) => (
    <div>
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</div>
      <ChartContainer config={config} className="aspect-auto w-full" style={{ height: 40 + list.length * 44 } as React.CSSProperties}>
        <BarChart data={list.map(toRow)} layout="vertical" margin={{ top: 4, right: 12, bottom: 0, left: 0 }} barCategoryGap={8}>
          <CartesianGrid horizontal={false} />
          <XAxis type="number" tickLine={false} axisLine={false} tickFormatter={compactTick} />
          <YAxis type="category" dataKey="label" tickLine={false} axisLine={false} width={110} />
          <ChartTooltip
            content={
              <ChartTooltipContent
                valueFormatter={(_v, key, item) => {
                  const i: Item = item.payload._i;
                  const mv = { net: i.net_sales, retainer: i.retainer_cost, commission: i.commission_cost, sample: i.sample_cost }[key as "net"];
                  return formatMV(mv);
                }}
                statusFor={(pl) => <>Contract: {pl[0].payload._i.contract_type}. Click a bar for evidence.</>}
              />
            }
          />
          <Bar dataKey="net" stackId="net" fill="var(--color-net)" isAnimationActive={false} cursor="pointer" onClick={(e: { payload?: Row }) => e?.payload && open(e.payload._i.net_sales.evidence_url, `Net sales · ${e.payload._i.handle}`)} />
          <Bar dataKey="retainer" stackId="cost" fill="var(--color-retainer)" isAnimationActive={false} cursor="pointer" onClick={(e: { payload?: Row }) => e?.payload && open(e.payload._i.retainer_cost.evidence_url, `Retainer · ${e.payload._i.handle}`)} />
          <Bar dataKey="commission" stackId="cost" fill="var(--color-commission)" isAnimationActive={false} cursor="pointer" onClick={(e: { payload?: Row }) => e?.payload && open(e.payload._i.commission_cost.evidence_url, `Commission · ${e.payload._i.handle}`)} />
          <Bar dataKey="sample" stackId="cost" fill="var(--color-sample)" isAnimationActive={false} cursor="pointer" onClick={(e: { payload?: Row }) => e?.payload && open(e.payload._i.sample_cost.evidence_url, `Sample cost · ${e.payload._i.handle}`)} />
        </BarChart>
      </ChartContainer>
    </div>
  );

  return (
    <ChartCard
      title="Creator economics"
      description="Net attributed sales vs known program costs, top and bottom creators by net sales."
      legend={
        <>
          <LegendItem color={T.netSales} label="Net sales" />
          <LegendItem color={T.grossGmv} label="Retainer" />
          <LegendItem color={T.attributedGmv} label="Commission" />
          <LegendItem color={T.refunds} label="Sample cost" />
        </>
      }
      info={{
        what: "Each top and bottom creator's net attributed sales next to the known cost of working with them.",
        how: "The first bar is net sales and the stacked bar beside it is retainer, commission and sample cost. Creators with an unknown cost are listed separately, never drawn as zero.",
        decision: "Helps you decide who to rebook, renegotiate with or drop.",
      }}
      dataRevision={revision}
    >
      {loading ? <Skeleton className="h-64 w-full" /> : error ? (
        <p className="text-xs text-rose-500">Could not load creators: {error instanceof Error ? error.message : String(error)}</p>
      ) : items.length === 0 ? (
        <p className="py-10 text-center text-xs text-muted-foreground">No creators for this selection.</p>
      ) : (
        <div className="space-y-4">
          {top.length > 0 ? panel("Top by net sales", top) : <p className="text-xs text-muted-foreground">No creator has both net sales and all costs known.</p>}
          {bottom.length > 0 && panel("Bottom by net sales", bottom)}
          <div className="border-t border-border pt-3">
            <div className="mb-1.5 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Cost unknown <StatusBadge status="unknown" label={`${unknown.length}`} />
            </div>
            {unknown.length === 0 ? <p className="text-xs text-muted-foreground">None</p> : (
              <ul className="divide-y divide-border border border-border text-xs">
                {unknown.map((i) => (
                  <li key={`${i.brand_id}-${i.creator_id}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-2 py-1.5">
                    <span className="font-medium">{i.handle}{!brandId && <span className="text-muted-foreground"> ({i.brand_id})</span>}</span>
                    <span className={`${MONO} text-muted-foreground`}>net {i.net_sales.value === null ? UNAVAILABLE : formatMoney(i.net_sales.value)}</span>
                    <span className={`${MONO} text-muted-foreground`}>
                      retainer {formatMV(i.retainer_cost)} · commission {formatMV(i.commission_cost)} · sample {formatMV(i.sample_cost)}
                    </span>
                    {(i.net_sales.status_reason || i.retainer_cost.status_reason) && <span className="text-muted-foreground">{i.net_sales.status_reason ?? i.retainer_cost.status_reason}</span>}
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
