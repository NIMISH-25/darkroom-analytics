"use client";
import { SampleFunnelChart } from "@/components/charts/SampleFunnelChart";
import { useEvidenceSheet } from "@/components/midday/EvidenceSheet";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatMV } from "@/lib/format";
import { useMeta, useSamples } from "@/lib/hooks";
import type { MV, Samples } from "@/lib/types";
import { Gated } from "./avail";
import { QueryState } from "./common";

const CELLS: [string, keyof Samples["counts"]][] = [
  ["Sent", "sent"], ["Delivered", "delivered"], ["Matched", "matched"], ["Pending", "pending"],
  ["No video", "no_video"], ["Unknown", "unknown"], ["Conversion rate", "conversion_rate"],
];

function Figure({ label, mv }: { label: string; mv: MV }) {
  const { open } = useEvidenceSheet();
  const known = mv.value !== null;
  const flagged = mv.status !== "current";
  const word = mv.status === "stale" ? "Stale" : "Incomplete";
  const reason = mv.status_reason ?? mv.data_note ?? "This figure may be missing some records.";
  return (
    <div className="flex min-w-0 flex-col gap-1.5 overflow-hidden p-4">
      <div className="truncate text-xs text-muted-foreground">{label}</div>
      {known ? (
        <button type="button" onClick={() => open(mv.evidence_url, label)} title="Show supporting numbers"
          className="self-start font-mono text-2xl tabular-nums tracking-tight underline decoration-dotted underline-offset-4 hover:decoration-solid">
          {formatMV(mv)}
        </button>
      ) : (
        <span className="text-sm text-muted-foreground">No data yet</span>
      )}
      {flagged && (
        <div>
          <Tooltip>
            <TooltipTrigger asChild>
              <span tabIndex={0} className="inline-block cursor-help focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring">
                <Badge variant={mv.status === "stale" ? "amber" : "orange"}>{word}</Badge>
              </span>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs whitespace-normal">{reason}</TooltipContent>
          </Tooltip>
        </div>
      )}
    </div>
  );
}

function BrandCard({ brandId, name }: { brandId: string; name?: string }) {
  const q = useSamples(brandId);
  const meta = useMeta().data;
  const title = name ?? meta?.brands.find((b) => b.brand_id === brandId)?.name ?? "";
  return (
    <section className="min-w-0 overflow-hidden border border-border bg-card">
      {title && <h3 className="border-b border-border px-4 py-3 text-sm font-medium">{title}</h3>}
      <QueryState q={q} rows={1}>
        {q.data && (
          <div className="grid grid-cols-2 divide-x divide-y divide-border sm:grid-cols-3 xl:grid-cols-7 xl:divide-y-0">
            {CELLS.map(([l, k]) => <Figure key={k} label={l} mv={q.data!.counts[k]} />)}
          </div>
        )}
      </QueryState>
    </section>
  );
}

export function BrandCounts({ brandId, title }: { brandId: string; title?: string }) {
  return <BrandCard brandId={brandId} name={title} />;
}

/** Brand samples tab: counts card + delivery-to-video lag chart (when available). */
export function BrandSamplesPanel({ brandId }: { brandId: string }) {
  return (
    <div className="space-y-4">
      <BrandCard brandId={brandId} name="" />
      <Gated brandId={brandId} series="sample_funnel_lag"><SampleFunnelChart brandId={brandId} /></Gated>
    </div>
  );
}

/** Portfolio samples: one card per brand and the portfolio lag chart. */
export function PortfolioSamples() {
  const meta = useMeta();
  return (
    <QueryState q={meta}>
      <div className="space-y-4">
        {(meta.data?.brands ?? []).map((b) => <BrandCard key={b.brand_id} brandId={b.brand_id} name={b.name} />)}
        <SampleFunnelChart brandId={null} />
      </div>
    </QueryState>
  );
}
