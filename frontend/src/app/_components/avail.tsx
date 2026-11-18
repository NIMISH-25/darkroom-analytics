"use client";
import type { ReactNode } from "react";
import { useChartsAvailable } from "@/lib/hooks";

/**
 * Mounts a chart only when the API availability classifier says `available` or `stale`.
 * `zero` / `unknown` render a one-line note; `empty` / `not_applicable` (and still loading) render nothing.
 * The UI never decides availability itself.
 */
export function Gated({ brandId, series, children }: { brandId: string; series: string; children: ReactNode }) {
  const q = useChartsAvailable(brandId);
  const s = (q.data as { series?: { series_id: string; status: string; reason: string | null }[] } | undefined)?.series?.find((x) => x.series_id === series);
  if (!s) return null;
  if (s.status === "available" || s.status === "stale") return <>{children}</>;
  if (s.status === "zero" || s.status === "unknown") {
    return (
      <p className="border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
        {s.reason ?? (s.status === "zero" ? "Nothing to show for this period: every value is zero." : "Nothing to show yet: the figures for this period are not known.")}
      </p>
    );
  }
  return null;
}
