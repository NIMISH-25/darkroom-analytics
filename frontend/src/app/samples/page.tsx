"use client";
import { PageHeader } from "@/components/midday/PageHeader";
import { PortfolioSamples } from "../_components/samples";

export default function Page() {
  return (
    <div className="space-y-4">
      <PageHeader title="Samples" />
      <PortfolioSamples />
    </div>
  );
}
