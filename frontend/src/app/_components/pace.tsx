"use client";
import { useState } from "react";
import { StatusBadge } from "@/components/midday/StatusBadge";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { BrandPace, BrandPaceCounts } from "./ext";

type Key = "on_track" | "behind" | "unknown";
const META: { key: Key; label: string; tone: string }[] = [
  { key: "on_track", label: "On track", tone: "text-emerald-600 dark:text-emerald-400" },
  { key: "behind", label: "Behind", tone: "text-rose-600 dark:text-rose-400" },
  { key: "unknown", label: "Unknown", tone: "text-muted-foreground" },
];

/** Maps the server's plain status label to a bucket (labels only, no numbers). */
function bucket(label: string): Key {
  const l = label.toLowerCase();
  if (l.includes("behind") || l.includes("off")) return "behind";
  if (l.includes("on track") || l.includes("on_track") || l.includes("ahead")) return "on_track";
  return "unknown";
}

export function BrandPaceWidget({ counts, brands }: { counts: BrandPaceCounts; brands: BrandPace[] }) {
  const [open, setOpen] = useState<Key | null>(null);
  const list = open ? brands.filter((b) => bucket(b.status_label) === open) : [];
  const title = META.find((m) => m.key === open)?.label;
  return (
    <>
      <div className="flex flex-wrap items-center gap-4 border border-border bg-card px-4 py-3 text-sm">
        <span className="font-medium">Brands on pace: <span className="font-mono tabular-nums tracking-tight">{counts.on_track}</span> of <span className="font-mono tabular-nums tracking-tight">{counts.total}</span></span>
        {META.map((m) => (
          <button key={m.key} type="button" onClick={() => setOpen(m.key)}
            className={`${m.tone} underline decoration-dotted underline-offset-2 hover:decoration-solid focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring`}>
            {m.label} <span className="font-mono tabular-nums tracking-tight">{counts[m.key]}</span>
          </button>
        ))}
      </div>
      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>{title} brands</SheetTitle>
            <SheetDescription>Brands in this state, with their goals.</SheetDescription>
          </SheetHeader>
          {list.length === 0 && <p className="text-sm text-muted-foreground">No brands are in this state.</p>}
          <ul className="space-y-4">
            {list.map((b) => (
              <li key={b.brand_slug} className="space-y-2 border border-border p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{b.brand_name}</span>
                  <StatusBadge status={bucket(b.status_label) === "on_track" ? "on_track" : bucket(b.status_label) === "behind" ? "off_track" : "unknown"} label={b.status_label} />
                </div>
                {b.data_note && <p className="text-sm text-muted-foreground">{b.data_note}</p>}
                <ul className="divide-y divide-border">
                  {b.goals.map((g, i) => (
                    <li key={i} className="space-y-1 py-2 text-sm">
                      <div className="flex items-center justify-between gap-2"><span>{g.goal_name}</span><span className="text-xs text-muted-foreground">{g.status_label}</span></div>
                      <div className="font-mono text-xs tabular-nums tracking-tight text-muted-foreground">
                        {g.actual_label ?? "No data yet"} of {g.target_label ?? "no target"}
                      </div>
                      {g.incomplete_reason && <p className="text-xs text-muted-foreground">{g.incomplete_reason}</p>}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </SheetContent>
      </Sheet>
    </>
  );
}
