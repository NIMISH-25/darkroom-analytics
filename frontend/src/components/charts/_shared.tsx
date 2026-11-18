"use client";
/* Shared helpers for chart components. No metric is computed here: only plotting conversions and layout. */
import type { ReactNode } from "react";
import { ReferenceArea } from "recharts";
import { HATCH_FILL } from "@/lib/chart-theme";
import { ChartCard } from "@/components/midday/ChartCard";
import { StatusBadge } from "@/components/midday/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { CHART_TOKENS } from "@/lib/chart-theme";
import type { ChartAvailability } from "@/lib/types";

export const T = CHART_TOKENS;
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
            <StatusBadge status={d.status} />
            <span className="text-muted-foreground">{d.status_reason ?? "Some of this data is stale or missing. Hatched regions are unknown, not zero."}</span>
          </div>
        )}
        {d.availability?.status === "unknown" && (
          <p className="text-xs text-muted-foreground">Values for this period are unknown. {d.availability.reason ?? ""} Hatched areas are missing data, not zero.</p>
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
