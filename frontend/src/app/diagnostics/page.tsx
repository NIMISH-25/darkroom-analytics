"use client";
import { Suspense } from "react";
import { PageHeader } from "@/components/midday/PageHeader";
import { DiagnosticsComparisonPanel } from "@/components/charts/DiagnosticsComparisonPanel";
import { CreatorConcentrationChart } from "@/components/charts/CreatorConcentrationChart";
import { RetainerCadenceChart } from "@/components/charts/RetainerCadenceChart";
import { useMeta } from "@/lib/hooks";
import { Gated } from "../_components/avail";
import { QueryState, Select, useUrlParams } from "../_components/common";

function Inner() {
  const meta = useMeta();
  const { get, set } = useUrlParams();
  const brands = meta.data?.brands ?? [];
  const brand = get("brand") || brands[0]?.brand_id || "";
  return (
    <div className="space-y-4">
      <PageHeader
        title="Diagnostics"
        actions={<Select label="Brand" value={brand} allLabel="Select" onChange={(v) => set({ brand: v })} options={brands.map((b) => ({ value: b.brand_id, label: b.name }))} />}
      />
      <QueryState q={meta}>
        {brand && (
          <div className="space-y-4" key={brand}>
            <DiagnosticsComparisonPanel brandId={brand} />
            <Gated brandId={brand} series="creator_concentration"><CreatorConcentrationChart brandId={brand} /></Gated>
            <Gated brandId={brand} series="retainer_cadence"><RetainerCadenceChart brandId={brand} /></Gated>
          </div>
        )}
      </QueryState>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={null}><Inner /></Suspense>;
}
