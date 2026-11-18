"use client";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ChartCard } from "@/components/midday/ChartCard";
import { StatusBadge } from "@/components/midday/StatusBadge";
import { useEvidenceSheet } from "@/components/midday/EvidenceSheet";
import { isMV } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";
import type { Diagnostics } from "@/lib/types";
import { NO_DATA, formatValue, MONO, T, compactTick, num, type ChartProps } from "./_shared";

const FACTOR_LABEL: Record<string, { label: string; unit: string }> = {
  active_creators: { label: "Active creators", unit: "count" },
  videos_per_creator: { label: "Videos per active creator", unit: "count" },
  gmv_per_video: { label: "Sales per video linked to a creator", unit: "USD" },
  unlinked_older_gmv: { label: "Sales from older or unlinked videos", unit: "USD" },
  A: { label: "Active creators", unit: "count" },
  V: { label: "Videos per active creator", unit: "count" },
  G: { label: "Sales per video linked to a creator", unit: "USD" },
};

/** One side of a comparison. Accepts {value, unavailable_reason}, a full MetricValue, or a bare value. */
interface Side { value: string | number | null; reason: string | null; url: string | null }
function side(v: unknown): Side {
  if (v === undefined || v === null) return { value: null, reason: null, url: null };
  if (typeof v === "object") {
    const o = v as { value?: string | number | null; unavailable_reason?: string | null; status_reason?: string | null; evidence_url?: string };
    return {
      value: o.value ?? null,
      reason: o.unavailable_reason ?? (isMV(v) ? v.status_reason : null) ?? null,
      url: isMV(v) ? v.evidence_url : (o.evidence_url ?? null),
    };
  }
  return { value: v as string | number, reason: null, url: null };
}

function periodText(p: unknown): string {
  const o = p as { start?: string; end?: string } | null | undefined;
  return o?.start && o?.end ? `${o.start} to ${o.end}` : "this period";
}

interface TRow { label: string; unit: string; baseline: Side; current: Side; effect: Side; bold?: boolean }

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
  else if (query.error || !d) body = <p className="text-xs text-rose-500">The comparison could not be loaded right now. Please try again.</p>;
  else {
    const periods = d.periods as Record<string, unknown>;
    const notes = ((d as unknown as { notes?: string[] }).notes ?? []).filter(Boolean);
    const all: TRow[] = [
      ...d.factors.map((f) => ({ label: (f as { label?: string }).label ?? FACTOR_LABEL[f.key]?.label ?? "Other factor", unit: FACTOR_LABEL[f.key]?.unit ?? "count", baseline: side(f.baseline), current: side(f.current), effect: side(f.effect) })),
      { label: (d.unlinked_older_gmv as { label?: string }).label ?? "Sales from older or unlinked videos", unit: "USD", baseline: side(d.unlinked_older_gmv.baseline), current: side(d.unlinked_older_gmv.current), effect: side(d.unlinked_older_gmv.delta) },
      { label: (d.total as { label?: string }).label ?? "Total sales", unit: "USD", baseline: side(d.total.baseline), current: side(d.total.current), effect: side(d.total.delta), bold: true },
    ];
    // Only rows that have a value on at least one side.
    const rows = all.filter((r) => r.baseline.value !== null || r.current.value !== null || r.effect.value !== null);
    const chartRows = rows.filter((r) => r.effect.value !== null).map((r) => ({ label: r.label, effect: num(r.effect.value), shown: formatValue(r.effect.value, "USD"), url: r.effect.url }));
    const config: ChartConfig = { effect: { label: "Effect on GMV", color: T.attributedGmv } };
    const incomplete = d.status !== "current";

    const cell = (s: Side, unit: string, key: string) => {
      if (s.value === null) {
        return (
          <TableCell className="text-right text-muted-foreground" key={key}>
            <span title={s.reason ?? "There is no data for this yet."} className="cursor-help underline decoration-dotted underline-offset-2">{NO_DATA}</span>
          </TableCell>
        );
      }
      const text = formatValue(s.value, unit);
      return (
        <TableCell className={`text-right ${MONO}`} key={key}>
          {s.url ? <button type="button" className="underline decoration-dotted underline-offset-2 hover:decoration-solid" onClick={() => open(s.url as string, key)}>{text}</button> : text}
        </TableCell>
      );
    };

    body = (
      <div className="space-y-4">
        <div className="border border-border bg-muted/40 px-3 py-2 text-sm font-medium">{d.disclaimer}</div>
        {incomplete && (
          <div className="flex items-center gap-2 text-xs">
            <StatusBadge status={d.status} title="Some figures are missing, so rows without data are left out." />
            <span className="text-muted-foreground">Some figures are missing, so rows without data are left out.</span>
          </div>
        )}
        {notes.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">{notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        )}
        <div className={`grid grid-cols-2 gap-px border border-border bg-border text-xs ${MONO}`}>
          <div className="bg-card p-2"><div className="font-sans text-muted-foreground">Before</div>{periodText(periods?.baseline)}</div>
          <div className="bg-card p-2"><div className="font-sans text-muted-foreground">Now</div>{periodText(periods?.current)}</div>
        </div>
        {rows.length === 0 ? (
          <p className="text-xs text-muted-foreground">There is no data yet to compare these two periods.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow><TableHead>Driver</TableHead><TableHead className="text-right">Before</TableHead><TableHead className="text-right">Now</TableHead><TableHead className="text-right">Effect on GMV</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.label} className={r.bold ? "font-medium" : undefined}>
                  <TableCell>{r.label}</TableCell>
                  {cell(r.baseline, r.unit, `${r.label} before`)}
                  {cell(r.current, r.unit, `${r.label} now`)}
                  {cell(r.effect, "USD", `${r.label} effect`)}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {chartRows.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">What moved GMV</div>
            <ChartContainer config={config} className="aspect-auto w-full" style={{ height: 40 + chartRows.length * 38 } as React.CSSProperties}>
              <BarChart data={chartRows} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid horizontal={false} />
                <XAxis type="number" tickLine={false} axisLine={false} tickFormatter={compactTick} tick={{ fontSize: 12 }} />
                <YAxis type="category" dataKey="label" tickLine={false} axisLine={false} width={190} tick={{ fontSize: 12 }} />
                <ReferenceLine x={0} stroke={T.target} strokeWidth={2.5} strokeDasharray="2 4" />
                <ChartTooltip content={<ChartTooltipContent hideLabel valueFormatter={(_v, _k, item) => item.payload.shown} statusFor={(pl) => <>{pl[0].payload.label}. Click for evidence.</>} />} />
                <Bar dataKey="effect" isAnimationActive={false} cursor="pointer" onClick={(e: { payload?: { label: string; url: string | null } }) => e?.payload?.url && open(e.payload.url, e.payload.label)}>
                  {chartRows.map((r, i) => <Cell key={i} fill={(r.effect ?? 0) < 0 ? T.statusError : T.attributedGmv} />)}
                </Bar>
              </BarChart>
            </ChartContainer>
          </div>
        )}
        <div>
          <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Product observations</div>
          <ul className="divide-y divide-border border border-border text-xs">
            {d.products.map((p) => (
              <li key={p.product_id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-2 py-1.5">
                <span className="min-w-[8rem] font-medium">{(p as { label?: string }).label ?? p.name}</span>
                <span className={`${MONO} text-muted-foreground`}>{formatValue(side(p.gmv_baseline).value, "USD")} to {formatValue(side(p.gmv_current).value, "USD")} ({formatValue(side(p.delta).value, "USD")})</span>
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
      description={d ? `${periodText((d.periods as Record<string, unknown>)?.current)} compared with ${periodText((d.periods as Record<string, unknown>)?.baseline)}` : "The current period compared with the same days of the previous month."}
      status={d?.status ?? null}
      info={{
        what: "Compares this period with the same days last month and splits the GMV change into its drivers.",
        how: "Bars to the right pushed GMV up and bars to the left pulled it down. Drivers with no data yet are left out. It describes what changed, not proof of why.",
        decision: "Points you at whether to fix creator count, posting volume or sales per video first.",
      }}
    >
      {body}
    </ChartCard>
  );
}
