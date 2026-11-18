"use client";
import { BrandTabs } from "@/components/midday/BrandTabs";
import { PageHeader } from "@/components/midday/PageHeader";
import { PacingTrajectoryChart } from "@/components/charts/PacingTrajectoryChart";
import { DailyGmvRefundsChart } from "@/components/charts/DailyGmvRefundsChart";
import { ReconciliationBreakdownChart } from "@/components/charts/ReconciliationBreakdownChart";
import { DiagnosticsComparisonPanel } from "@/components/charts/DiagnosticsComparisonPanel";
import { CreatorConcentrationChart } from "@/components/charts/CreatorConcentrationChart";
import { RetainerCadenceChart } from "@/components/charts/RetainerCadenceChart";
import { useMeta } from "@/lib/hooks";
import { Gated } from "../../../_components/avail";
import { BrandKpiStrip } from "../../../_components/kpis";
import { QueryState } from "../../../_components/common";
import { CreatorsTable, useBrandCreators } from "../../../_components/creators";
import { BrandSamplesPanel } from "../../../_components/samples";
import { HealthSections } from "../../../_components/health";

function CreatorsTab({ brandId }: { brandId: string }) {
  const c = useBrandCreators(brandId);
  return (
    <div className="border border-border bg-card">
      <QueryState q={c}><CreatorsTable rows={c.rows} contractTypes={c.contractTypes} showBrand={false} /></QueryState>
    </div>
  );
}

export function BrandPage({ brandId }: { brandId: string }) {
  const meta = useMeta();
  const brand = meta.data?.brands.find((b) => b.brand_id === brandId);
  if (meta.data && !brand) {
    return <div role="alert" className="border border-border p-4 text-sm">Unknown brand &quot;{brandId}&quot;.</div>;
  }
  return (
    <div className="space-y-2">
      <PageHeader title={brand?.name ?? brandId} />
      <BrandTabs
        brandId={brandId}
        panels={{
          overview: (
            <div className="space-y-4">
              <BrandKpiStrip brandId={brandId} />
              <Gated brandId={brandId} series="pacing_trajectory"><PacingTrajectoryChart brandId={brandId} /></Gated>
              <Gated brandId={brandId} series="daily_gmv_refunds"><DailyGmvRefundsChart brandId={brandId} /></Gated>
              <Gated brandId={brandId} series="attribution_reconciliation"><ReconciliationBreakdownChart brandId={brandId} /></Gated>
            </div>
          ),
          creators: <CreatorsTab brandId={brandId} />,
          samples: <BrandSamplesPanel brandId={brandId} />,
          diagnostics: (
            <div className="space-y-4">
              <DiagnosticsComparisonPanel brandId={brandId} />
              <Gated brandId={brandId} series="creator_concentration"><CreatorConcentrationChart brandId={brandId} /></Gated>
              <Gated brandId={brandId} series="retainer_cadence"><RetainerCadenceChart brandId={brandId} /></Gated>
            </div>
          ),
          health: <HealthSections brandId={brandId} />,
        }}
      />
    </div>
  );
}
