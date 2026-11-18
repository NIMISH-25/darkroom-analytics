"use client";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ChartCard } from "@/components/midday/ChartCard";
import { StatusBadge } from "@/components/midday/StatusBadge";
import { useEvidenceSheet } from "@/components/midday/EvidenceSheet";
import { HATCH_FILL } from "@/lib/chart-theme";
import { UNAVAILABLE, formatVal, isMV } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";
import type { Diagnostics, Val } from "@/lib/types";
import { MONO, T, compactTick, num, type ChartProps } from "./_shared";

const FACTOR_LABEL: Record<string, { label: string; unit: string }> = {
  A: { label: "Active creators", unit: "count" },
  V: { label: "Videos per active creator", unit: "count" },
  G: { label: "GMV per linked video", unit: "USD" },
};

const raw = (v: Val | undefined) => (v === undefined || v === null ? null : isMV(v) ? v.value : v);
const evUrl = (v: Val | undefined) => (isMV(v) ? v.evidence_url : null);

function periodText(p: unknown): string {
  const o = p as { start?: string; end?: string } | null | undefined;
  return o?.start && o?.end ? `${o.start} to ${o.end}` : UNAVAILABLE;
}

type Row = { label: string; effect: number | null; shown: string; url: string | null };

export function DiagnosticsComparisonPanel({ brandId, month, cutoff }: ChartProps) {
  const qs = new URLSearchParams();
  if (month) qs.set("month", month);
  if (cutoff) qs.set("cutoff", cutoff);
  const q = qs.toString();
  const query = useApiQuery<Diagnostics>(brandId ? `/api/v1/brands/${brandId}/diagnostics${q ? `?${q}` : ""}` : null);
  const { open } = useEvidenceSheet();
  const d = query.data;

  let body;
  if (!brandId) body = <p className="py-10 text-center text-xs text-muted-foreground">Select a brand to see its diagnostics.</p>;
  else if (query.isLoading || (!d && !query.error)) body = <Skeleton className="h-64 w-full" />;
  else if (query.error || !d) body = <p className="text-xs text-rose-500">Could not load diagnostics: {query.error instanceof Error ? query.error.message : String(query.error)}</p>;
  else {
    const periods = d.periods as Record<string, unknown>;
    const rows: Row[] = [
      ...d.factors.map((f) => ({ label: FACTOR_LABEL[f.key]?.label ?? f.key, effect: num(raw(f.effect)), shown: formatVal(f.effect, "USD"), url: evUrl(f.effect) })),
      { label: "Unlinked / older GMV", effect: num(raw(d.unlinked_older_gmv.delta)), shown: formatVal(d.unlinked_older_gmv.delta, "USD"), url: evUrl(d.unlinked_older_gmv.delta) },
      { label: "Total change", effect: num(raw(d.total.delta)), shown: formatVal(d.total.delta, "USD"), url: evUrl(d.total.delta) },
    ];
    const config: ChartConfig = { effect: { label: "Effect on GMV", color: T.attributedGmv } };
    const incomplete = d.status !== "current";
    const cell = (v: Val | undefined, unit: string, key: string) => {
      const url = evUrl(v);
      const text = formatVal(v, unit);
      return (
        <TableCell className={`text-right ${MONO} ${text === UNAVAILABLE ? "text-muted-foreground" : ""}`} key={key}>
          {url ? <button type="button" className="underline decoration-dotted underline-offset-2 hover:decoration-solid" onClick={() => open(url, key)}>{text}</button> : text}
        </TableCell>
      );
    };
    body = (
      <div className="space-y-4">
        <div className="border border-border bg-muted/40 px-3 py-2 text-xs font-medium">{d.disclaimer}</div>
        {incomplete && (
          <div className="flex items-center gap-2 text-xs"><StatusBadge status={d.status} /><span className="text-muted-foreground">Inputs are incomplete. Effects that cannot be decomposed show UNAVAILABLE.</span></div>
        )}
        <div className={`grid grid-cols-2 gap-px border border-border bg-border text-xs ${MONO}`}>
          <div className="bg-card p-2"><div className="font-sans text-muted-foreground">Baseline</div>{periodText(periods?.baseline)}</div>
          <div className="bg-card p-2"><div className="font-sans text-muted-foreground">Current</div>{periodText(periods?.current)}</div>
        </div>
        <Table>
          <TableHeader>
            <TableRow><TableHead>Driver</TableHead><TableHead className="text-right">Baseline</TableHead><TableHead className="text-right">Current</TableHead><TableHead className="text-right">Effect on GMV</TableHead></TableRow>
          </TableHeader>
          <TableBody>
            {d.factors.map((f) => {
              const m = FACTOR_LABEL[f.key] ?? { label: f.key, unit: "count" };
              return (
                <TableRow key={f.key}>
                  <TableCell>{m.label}</TableCell>
                  {cell(f.baseline, m.unit, `${m.label} baseline`)}
                  {cell(f.current, m.unit, `${m.label} current`)}
                  {cell(f.effect, "USD", `${m.label} effect`)}
                </TableRow>
              );
            })}
            <TableRow>
              <TableCell>Unlinked / older GMV</TableCell>
              {cell(d.unlinked_older_gmv.baseline, "USD", "Unlinked baseline")}
              {cell(d.unlinked_older_gmv.current, "USD", "Unlinked current")}
              {cell(d.unlinked_older_gmv.delta, "USD", "Unlinked change")}
            </TableRow>
            <TableRow className="font-medium">
              <TableCell>Total GMV</TableCell>
              {cell(d.total.baseline, "USD", "Total baseline")}
              {cell(d.total.current, "USD", "Total current")}
              {cell(d.total.delta, "USD", "Total change")}
            </TableRow>
          </TableBody>
        </Table>
        <div>
          <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Effects on GMV (method: {d.method})</div>
          <ChartContainer config={config} className="aspect-auto w-full" style={{ height: 40 + rows.length * 38 } as React.CSSProperties}>
            <BarChart data={rows.map((r) => ({ ...r, tick: r.effect === null ? `${r.label} (${UNAVAILABLE})` : r.label }))} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid horizontal={false} />
              <XAxis type="number" tickLine={false} axisLine={false} tickFormatter={compactTick} />
              <YAxis type="category" dataKey="tick" tickLine={false} axisLine={false} width={190} />
              <ReferenceLine x={0} stroke={T.target} strokeWidth={2.5} strokeDasharray="2 4" />
              <ChartTooltip content={<ChartTooltipContent hideLabel valueFormatter={(_v, _k, item) => item.payload.shown} statusFor={(pl) => <>{pl[0].payload.label}. Click for evidence.</>} />} />
              <Bar dataKey="effect" isAnimationActive={false} cursor="pointer" minPointSize={0} onClick={(e: { payload?: Row }) => e?.payload?.url && open(e.payload.url, e.payload.label)}>
                {rows.map((r, i) => (
                  <Cell key={i} fill={r.effect === null ? HATCH_FILL : r.effect < 0 ? T.statusError : T.attributedGmv} />
                ))}
              </Bar>
            </BarChart>
          </ChartContainer>
        </div>
        <div>
          <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Product observations</div>
          <ul className="divide-y divide-border border border-border text-xs">
            {d.products.map((p) => (
              <li key={p.product_id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-2 py-1.5">
                <span className="min-w-[8rem] font-medium">{p.name}</span>
                <span className={`${MONO} text-muted-foreground`}>{formatVal(p.gmv_baseline)} to {formatVal(p.gmv_current)} ({formatVal(p.delta)})</span>
                <span className="text-muted-foreground">{p.observation}</span>
              </li>
            ))}
            {d.products.length === 0 && <li className="px-2 py-1.5 text-muted-foreground">No product observations.</li>}
          </ul>
        </div>
      </div>
    );
  }

  return (
    <ChartCard
      title="Where it broke: period comparison"
      description={d ? `${periodText((d.periods as Record<string, unknown>)?.current)} vs ${periodText((d.periods as Record<string, unknown>)?.baseline)}` : "Current period vs the same days of the previous month."}
      status={d?.status ?? null}
      info={{
        what: "Compares this period with the same days last month and splits the GMV change into its drivers.",
        how: "Bars to the right pushed GMV up and bars to the left pulled it down. A hatched bar means that driver could not be worked out from the data; it describes what changed, not proof of why.",
        decision: "Points you at whether to fix creator count, posting volume or sales per video first.",
      }}
    >
      {body}
    </ChartCard>
  );
}
