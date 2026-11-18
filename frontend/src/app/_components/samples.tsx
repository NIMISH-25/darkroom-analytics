"use client";
import { MetricValue } from "@/components/midday/MetricValue";
import { SampleFunnelChart } from "@/components/charts/SampleFunnelChart";
import { useMeta, useSamples } from "@/lib/hooks";
import type { Samples } from "@/lib/types";
import { Gated } from "./avail";
import { QueryState } from "./common";

function CountsStrip({ counts }: { counts: Samples["counts"] }) {
  const cells: [string, keyof Samples["counts"]][] = [
    ["Sent", "sent"], ["Delivered", "delivered"], ["Matched", "matched"], ["Pending", "pending"],
    ["No video", "no_video"], ["Unknown", "unknown"], ["Conversion rate", "conversion_rate"],
  ];
  return (
    <div className="flex flex-wrap divide-x divide-border border border-border bg-card">
      {cells.map(([l, k]) => (
        <div key={k} className="min-w-[130px] flex-1 p-4">
          <div className="text-xs text-muted-foreground">{l}</div>
          <MetricValue mv={counts[k]} label={l} className="text-lg" />
        </div>
      ))}
    </div>
  );
}

export function BrandCounts({ brandId, title }: { brandId: string; title?: string }) {
  const q = useSamples(brandId);
  return (
    <QueryState q={q} rows={1}>
      {q.data && (
        <div className="space-y-2">
          {title && <h3 className="text-sm font-medium">{title}</h3>}
          <CountsStrip counts={q.data.counts} />
        </div>
      )}
    </QueryState>
  );
}

/** Brand samples tab: counts strip + delivery-to-video lag chart (when available). */
export function BrandSamplesPanel({ brandId }: { brandId: string }) {
  return (
    <div className="space-y-4">
      <BrandCounts brandId={brandId} />
      <Gated brandId={brandId} series="sample_funnel_lag"><SampleFunnelChart brandId={brandId} /></Gated>
    </div>
  );
}

/** Portfolio samples: each brand's counts (API values) and the portfolio lag chart. */
export function PortfolioSamples() {
  const meta = useMeta();
  return (
    <QueryState q={meta}>
      <div className="space-y-4">
        {(meta.data?.brands ?? []).map((b) => <BrandCounts key={b.brand_id} brandId={b.brand_id} title={b.name} />)}
        <SampleFunnelChart brandId={null} />
      </div>
    </QueryState>
  );
}
