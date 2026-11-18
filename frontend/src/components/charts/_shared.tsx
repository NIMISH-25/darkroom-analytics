"use client";
/* Shared helpers for chart components. No metric is computed here: only plotting conversions and layout. */
import { useEffect, useState, type ReactNode } from "react";
import { ReferenceArea } from "recharts";
import { HATCH_FILL } from "@/lib/chart-theme";
import { ChartCard } from "@/components/midday/ChartCard";
import { StatusBadge } from "@/components/midday/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { CHART_TOKENS } from "@/lib/chart-theme";
import * as fmt from "@/lib/format";
import type { MV, Val } from "@/lib/types";
import type { ChartAvailability } from "@/lib/types";

export const T = CHART_TOKENS;

/** Operator wording: the bare placeholder never reaches the screen. */
export const NO_DATA = "No data yet";
const nd = (t: string) => (t === fmt.UNAVAILABLE ? NO_DATA : t);
export const UNAVAILABLE = NO_DATA;
export const formatMoney = (v: string | number | null | undefined) => nd(fmt.formatMoney(v));
export const formatCount = (v: string | number | null | undefined) => nd(fmt.formatCount(v));
export const formatPercent = (v: string | number | null | undefined) => nd(fmt.formatPercent(v));
export const formatValue = (v: string | number | null | undefined, unit?: string) => nd(fmt.formatValue(v, unit));
export const formatMV = (mv: MV | null | undefined) => nd(fmt.formatMV(mv));
export const formatVal = (v: Val | undefined, unit?: string) => nd(fmt.formatVal(v, unit));
export interface Info { what: string; how: string; decision: string }

export interface ChartProps {
  brandId: string | null;
  month?: string;
  cutoff?: string;
}

/** Decimal string -> number for plotting position only. null stays null (a gap), never 0. */
export function num(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** Axis tick label only (formatting, not a metric). */
export function compactTick(v: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

/** Anything that is not current or forecast (missing, stale, partial, unknown, null) is uncovered and hatched. */
export const uncovered = (status: string | null | undefined) => status !== "current" && status !== "forecast";
/** Y domain that stays valid when every value is null (fallback axis only; never a metric). */
export const safeDomain = ([, max]: [number, number]): [number, number] => [0, Number.isFinite(max) && max > 0 ? max : 1];

export const MONO = "font-mono tabular-nums tracking-tight";

/** Contiguous runs of hatched (stale / missing / partial) points, as x1..x2 pairs. Singletons widen to the neighbours so the band is visible. */
export function hatchRanges<P extends { x: string | number; status: string }>(points: P[]): { x1: string | number; x2: string | number }[] {
  const out: { x1: string | number; x2: string | number }[] = [];
  let i = 0;
  while (i < points.length) {
    if (uncovered(points[i].status)) {
      let j = i;
      while (j + 1 < points.length && uncovered(points[j + 1].status)) j++;
      if (i === j) {
        out.push({ x1: points[Math.max(0, i - 1)].x, x2: points[Math.min(points.length - 1, j + 1)].x });
      } else out.push({ x1: points[i].x, x2: points[j].x });
      i = j + 1;
    } else i++;
  }
  return out;
}

interface QueryLike<E> {
  data?: E;
  isLoading: boolean;
  error: unknown;
}

/** ChartCard with the standard loading / error / empty / stale states. */
export function ChartFrame<E extends { availability?: ChartAvailability; status: string; status_reason: string | null; coverage_through: string | null; data_revision: number; points?: unknown[] }>({
  title, description, legend, info, query, empty, emptyWhen, className, headerExtra, children,
}: {
  title: string;
  description?: ReactNode;
  legend?: ReactNode;
  info?: Info;
  query: QueryLike<E>;
  empty?: string;
  emptyWhen?: (d: E) => boolean;
  className?: string;
  headerExtra?: ReactNode;
  children: (data: E) => ReactNode;
}) {
  const d = query.data;
  let body: ReactNode;
  if (query.isLoading || (!d && !query.error)) {
    body = <Skeleton className="h-64 w-full" />;
  } else if (query.error || !d) {
    body = <p className="text-xs text-rose-500">Could not load chart: {query.error instanceof Error ? query.error.message : String(query.error)}</p>;
  } else if (d.availability && (d.availability.status === "empty" || d.availability.status === "not_applicable")) {
    return null; // contract: draw nothing
  } else if (d.availability && d.availability.status === "zero") {
    body = (
      <p className="py-6 text-center text-sm text-muted-foreground">
        Every value in this period is zero.{d.availability.reason ? ` ${d.availability.reason}` : ""}
      </p>
    );
  } else if (emptyWhen ? emptyWhen(d) : !d.points || d.points.length === 0) {
    body = <p className="py-10 text-center text-xs text-muted-foreground">{empty ?? "No data for this selection."}</p>;
  } else {
    body = (
      <div className="space-y-3">
        {d.status !== "current" && d.status !== "forecast" && (
          <div className="flex items-center gap-2 border border-border bg-muted/40 px-2 py-1.5 text-xs">
            <StatusBadge status={d.status} title={d.status_reason ?? "Some of this data is late or missing."} />
            <span className="text-muted-foreground">{d.status_reason ?? "Some of this data is late or missing. Hatched regions have no data, which is not the same as zero."}</span>
          </div>
        )}
        {d.availability?.status === "unknown" && (
          <p className="text-xs text-muted-foreground">No data yet for this period. {d.availability.reason ?? ""} Hatched areas have no data, which is not the same as zero.</p>
        )}
        {children(d)}
      </div>
    );
  }
  return (
    <ChartCard
      title={title}
      description={description}
      legend={legend}
      info={info}
      className={className}
      status={d?.status ?? null}
      coverageThrough={d ? d.coverage_through : undefined}
      dataRevision={d?.data_revision}
    >
      {headerExtra}
      {body}
    </ChartCard>
  );
}

export function Swatch({ color, hatched }: { color: string; hatched?: boolean }) {
  return (
    <span className="inline-block h-2 w-2 shrink-0 border border-border" style={{ background: hatched ? "repeating-linear-gradient(45deg, hsl(var(--muted-foreground)) 0 1px, transparent 1px 3px)" : color }} />
  );
}

export function LegendItem({ color, label, hatched }: { color: string; label: string; hatched?: boolean }) {
  return <span className="inline-flex items-center gap-1.5"><Swatch color={color} hatched={hatched} />{label}</span>;
}

/** Colors by status for sample/coverage states only. */
export const STATE_COLORS = {
  converted: CHART_TOKENS.statusOk,
  pending: CHART_TOKENS.statusWarn,
  suspect: CHART_TOKENS.projection,
  no_video: CHART_TOKENS.statusError,
  unknown: CHART_TOKENS.statusUnknown,
  in_transit: CHART_TOKENS.grossGmv,
} as const;

/** Hatched overlays for every contiguous missing/stale/partial x range. Call as a function (not a component) inside a Recharts chart. */
export function hatchAreas<P extends { x: string | number; status: string }>(points: P[]) {
  return hatchRanges(points).map((r, i) => (
    <ReferenceArea
      key={`hatch-${i}`}
      x1={r.x1 as string}
      x2={r.x2 as string}
      ifOverflow="visible"
      shape={((p: { x?: number; y?: number; width?: number; height?: number }) => (
        <rect
          data-testid="missing-hatch"
          aria-label={`Missing data: ${r.x1} to ${r.x2}`}
          x={p.x} y={p.y} width={Math.max(p.width ?? 0, 6)} height={p.height}
          fill={HATCH_FILL}
        />
      )) as never}
    />
  ));
}

/** Hatched stand-in plot for a series with no values at all (no scale can be drawn). Axes ends and a hatch region cover the whole range. */
export function AllMissingPlot({ xs, height = 288, note }: { xs: string[]; height?: number; note?: string }) {
  const first = xs[0], last = xs[xs.length - 1];
  return (
    <div className="w-full" role="img" aria-label={`Missing data: ${first} to ${last}`}>
      <div className="flex" style={{ height }}>
        <span className="w-10 shrink-0 self-end pr-2 text-right font-mono text-xs text-muted-foreground">0</span>
        <div
          data-testid="missing-hatch"
          aria-label={`Missing data: ${first} to ${last}`}
          className="relative flex-1 border-b border-l border-border"
          style={{ background: "repeating-linear-gradient(45deg, hsl(var(--muted-foreground) / 0.45) 0 2px, transparent 2px 6px)" }}
        >
          {note && <span className="absolute left-2 top-2 bg-background px-1.5 py-0.5 text-xs text-muted-foreground">{note}</span>}
        </div>
      </div>
      <div className="flex justify-between pl-10 pt-1 font-mono text-xs text-muted-foreground"><span>{first?.slice(5)}</span><span>{last?.slice(5)}</span></div>
    </div>
  );
}

/** True while the document uses the dark theme. */
export function useIsDark(): boolean {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const el = document.documentElement;
    const update = () => setDark(el.classList.contains("dark"));
    update();
    const mo = new MutationObserver(update);
    mo.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, []);
  return dark;
}
