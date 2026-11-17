"use client";
import { Suspense, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PagePlaceholder } from "./PageHeader";

export const BRAND_TABS = [
  { key: "overview", label: "Overview & Pacing" },
  { key: "creators", label: "Creators & Economics" },
  { key: "samples", label: "Samples & Funnel" },
  { key: "diagnostics", label: "Diagnostics & Insights" },
  { key: "health", label: "Data Health" },
] as const;
export type BrandTabKey = (typeof BRAND_TABS)[number]["key"];

export interface BrandTabsProps {
  brandId: string;
  /** Content per tab; missing tabs render a titled placeholder. */
  panels?: Partial<Record<BrandTabKey, ReactNode>>;
}

function Inner({ brandId, panels = {} }: BrandTabsProps) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const raw = params.get("tab");
  const tab: BrandTabKey = BRAND_TABS.some((t) => t.key === raw) ? (raw as BrandTabKey) : "overview";

  function change(next: string) {
    const p = new URLSearchParams(params.toString());
    p.set("tab", next);
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  }

  return (
    <Tabs value={tab} onValueChange={change}>
      <TabsList>
        {BRAND_TABS.map((t) => <TabsTrigger key={t.key} value={t.key}>{t.label}</TabsTrigger>)}
      </TabsList>
      {BRAND_TABS.map((t) => (
        <TabsContent key={t.key} value={t.key}>
          {panels[t.key] ?? <PagePlaceholder title={`${t.label} · ${brandId}`} />}
        </TabsContent>
      ))}
    </Tabs>
  );
}

/** URL-synced (?tab=overview|creators|samples|diagnostics|health) brand tabs. */
export function BrandTabs(props: BrandTabsProps) {
  return <Suspense fallback={null}><Inner {...props} /></Suspense>;
}
