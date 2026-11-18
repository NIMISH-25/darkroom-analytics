"use client";
import { useState } from "react";
import { StatusBadge } from "@/components/midday/StatusBadge";
import { useEvidenceSheet } from "@/components/midday/EvidenceSheet";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { formatMoney } from "@/lib/format";
import { useAttention, useMeta } from "@/lib/hooks";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { QueryState } from "./common";
import type { AttentionItemExt } from "./ext";

export const KIND_LABEL: Record<string, string> = {
  quiet_retainer: "Quiet retainer", sample_no_video: "Sample, no video", missing_source: "Missing source",
};

function Block({ title, children }: { title: string; children: string | null | undefined }) {
  if (!children) return null;
  return (
    <section className="space-y-1 border-t border-border pt-3">
      <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h4>
      <p className="text-sm">{children}</p>
    </section>
  );
}

function AttentionSheet({ item, brand, onClose }: { item: AttentionItemExt | null; brand: string; onClose: () => void }) {
  const { open } = useEvidenceSheet();
  return (
    <Sheet open={item !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent>
        {item && (
          <>
            <SheetHeader>
              <SheetTitle>{item.title}</SheetTitle>
              <SheetDescription>{brand}{item.creator_name ? ` · ${item.creator_name}` : ""}</SheetDescription>
            </SheetHeader>
            <Block title="Why it needs attention">{item.why_needs_attention}</Block>
            <Block title="What to do">{item.what_to_do}</Block>
            <Block title="Incomplete data">{item.incomplete_reason}</Block>
            <Block title="Note">{item.data_note}</Block>
            <div className="border-t border-border pt-3">
              <Button variant="outline" onClick={() => { const u = item.evidence_url, t = item.title; onClose(); open(u, t); }}>Show supporting numbers</Button>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

export function AttentionTable({ items, compact }: { items: AttentionItemExt[]; compact?: boolean }) {
  const meta = useMeta().data;
  const [sel, setSel] = useState<AttentionItemExt | null>(null);
  const name = (i: AttentionItemExt) => i.brand_name ?? meta?.brands.find((b) => b.brand_id === i.brand_id)?.name ?? "";
  if (items.length === 0) return <p className="p-4 text-sm text-muted-foreground">Nothing needs attention.</p>;
  const activate = (i: AttentionItemExt) => setSel(i);
  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-12">Rank</TableHead>
            <TableHead>Item</TableHead>
            {!compact && <TableHead>Kind</TableHead>}
            <TableHead>Brand</TableHead>
            <TableHead className="text-right">Impact</TableHead>
            {!compact && <TableHead>Basis</TableHead>}
            {!compact && <TableHead>Period</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((i) => (
            <TableRow
              key={i.item_id} role="button" tabIndex={0} className="cursor-pointer focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring"
              aria-label={`Open details: ${i.title}`}
              onClick={() => activate(i)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(i); } }}
            >
              <TableCell className="font-mono tabular-nums tracking-tight">{i.rank}</TableCell>
              <TableCell>{i.title}</TableCell>
              {!compact && <TableCell><StatusBadge status="unknown" label={KIND_LABEL[i.kind] ?? "Other"} /></TableCell>}
              <TableCell>{name(i)}</TableCell>
              <TableCell className="text-right font-mono tabular-nums tracking-tight">
                {i.impact_score === null ? <span className="font-sans text-muted-foreground">Not estimated</span> : formatMoney(i.impact_score)}
              </TableCell>
              {!compact && <TableCell className="text-muted-foreground">{i.impact_basis}</TableCell>}
              {!compact && <TableCell className="font-mono tabular-nums tracking-tight">{i.period_start} to {i.period_end}</TableCell>}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <AttentionSheet item={sel} brand={sel ? name(sel) : ""} onClose={() => setSel(null)} />
    </>
  );
}

/** Ranked top-N strip (items already ranked by the API; sliced only). */
export function NeedsAttentionStrip({ limit = 5 }: { limit?: number }) {
  const q = useAttention();
  return (
    <QueryState q={q}>
      {q.data && <AttentionTable items={q.data.items.slice(0, limit) as AttentionItemExt[]} compact />}
    </QueryState>
  );
}
