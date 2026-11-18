"use client";
import { Suspense, useMemo } from "react";
import { PageHeader } from "@/components/midday/PageHeader";
import { useAttention, useMeta } from "@/lib/hooks";
import { AttentionTable, KIND_LABEL } from "../_components/attention";
import { QueryState, Section, Select, useUrlParams } from "../_components/common";

function Inner() {
  const { get, set } = useUrlParams();
  const kind = get("kind"), brand = get("brand");
  const q = useAttention();
  const meta = useMeta().data;
  const items = useMemo(() => (q.data?.items ?? []).filter((i) => (!kind || i.kind === kind) && (!brand || i.brand_id === brand)), [q.data, kind, brand]);
  return (
    <div className="space-y-4">
      <PageHeader title="Attention" description="Ranked across brands by impact score (USD exposure; unknown last). Each item links to its evidence." />
      <Section
        title="Needs attention"
        actions={
          <div className="flex flex-wrap gap-3">
            <Select label="Kind" value={kind} onChange={(v) => set({ kind: v })} options={Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }))} />
            <Select label="Brand" value={brand} onChange={(v) => set({ brand: v })} options={(meta?.brands ?? []).map((b) => ({ value: b.brand_id, label: b.name }))} />
          </div>
        }
      >
        <QueryState q={q}><AttentionTable items={items} /></QueryState>
      </Section>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={null}><Inner /></Suspense>;
}
