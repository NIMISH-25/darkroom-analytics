"use client";
import { PageHeader } from "@/components/midday/PageHeader";
import { HealthSections } from "../_components/health";

export default function Page() {
  return (
    <div className="space-y-4">
      <PageHeader title="Data health" />
      <HealthSections />
    </div>
  );
}
