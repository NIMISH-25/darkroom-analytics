"use client";
import Link from "next/link";
import { PageHeader } from "@/components/midday/PageHeader";
import { StatusBadge } from "@/components/midday/StatusBadge";
import { PacingTrajectoryChart } from "@/components/charts/PacingTrajectoryChart";
import { useOverview } from "@/lib/hooks";
import { NeedsAttentionStrip } from "../_components/attention";
import { QueryState, Section } from "../_components/common";
import { PortfolioKpiStrip } from "../_components/kpis";

/** Navigation tiles: name, pace status and coverage badge (API values only). */
function BrandTiles() {
  const ov = useOverview();
  return (
    <QueryState q={ov} rows={1}>
      <nav aria-label="Brands" className="grid grid-cols-1 gap-px border border-border bg-border sm:grid-cols-2 xl:grid-cols-5">
        {ov.data?.brands.map((b) => {
          const g = b.goals[0];
          return (
            <Link key={b.brand_id} href={`/brands/${b.brand_id}`} className="flex flex-col gap-2 bg-card p-4 hover:bg-accent/50 focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring">
              <span className="text-sm font-medium">{b.name}</span>
              <span className="flex flex-wrap items-center gap-2">
                {g ? <StatusBadge status={g.pace_status} /> : <StatusBadge status="unknown" />}
                {g ? <StatusBadge status={g.actual.status} title={g.actual.coverage_through ? `coverage through ${g.actual.coverage_through}` : undefined} /> : null}
              </span>
            </Link>
          );
        })}
      </nav>
    </QueryState>
  );
}

export default function Page() {
  return (
    <div className="space-y-4">
      <PageHeader title="Overview" />
      <PortfolioKpiStrip />
      <PacingTrajectoryChart brandId={null} />
      <BrandTiles />
      <Section title="Needs attention">
        <NeedsAttentionStrip limit={6} />
        <div className="border-t border-border px-4 py-3 text-sm"><Link href="/attention" className="text-muted-foreground hover:text-foreground">See all &rarr;</Link></div>
      </Section>
    </div>
  );
}
