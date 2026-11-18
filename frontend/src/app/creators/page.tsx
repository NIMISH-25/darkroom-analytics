"use client";
import { Suspense } from "react";
import { PageHeader } from "@/components/midday/PageHeader";
import { CreatorEconomicsChart } from "@/components/charts/CreatorEconomicsChart";
import { useMeta } from "@/lib/hooks";
import { QueryState } from "../_components/common";
import { CreatorsTable, useAllCreators } from "../_components/creators";

function Inner() {
  const all = useAllCreators();
  const meta = useMeta().data;
  return (
    <div className="space-y-4">
      <PageHeader title="Creators" />
      <CreatorEconomicsChart brandId={null} />
      <div className="border border-border bg-card">
        <QueryState q={all}>
          <CreatorsTable
            rows={all.rows} contractTypes={all.contractTypes} showBrand
            brandOptions={(meta?.brands ?? []).map((b) => ({ value: b.brand_id, label: b.name }))}
          />
        </QueryState>
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={null}><Inner /></Suspense>;
}
