"use client";
import { StatusBadge } from "@/components/midday/StatusBadge";
import { useEvidenceSheet } from "@/components/midday/EvidenceSheet";
import { formatMoney, UNAVAILABLE } from "@/lib/format";
import { useAttention, useMeta } from "@/lib/hooks";
import type { AttentionItem } from "@/lib/types";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { QueryState } from "./common";

export const KIND_LABEL: Record<string, string> = {
  quiet_retainer: "Quiet retainer", sample_no_video: "Sample, no video", missing_source: "Missing source",
};

export function AttentionTable({ items, compact }: { items: AttentionItem[]; compact?: boolean }) {
  const { open } = useEvidenceSheet();
  const meta = useMeta().data;
  const name = (id: string) => meta?.brands.find((b) => b.brand_id === id)?.name ?? id;
  if (items.length === 0) return <p className="p-4 text-sm text-muted-foreground">Nothing needs attention.</p>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-12">Rank</TableHead>
          <TableHead>Item</TableHead>
          {!compact && <TableHead>Kind</TableHead>}
          <TableHead>Brand</TableHead>
          <TableHead className="text-right">Impact score</TableHead>
          {!compact && <TableHead>Basis</TableHead>}
          {!compact && <TableHead>Period</TableHead>}
          <TableHead className="w-20">Evidence</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((i) => (
          <TableRow key={i.item_id}>
            <TableCell className="font-mono tabular-nums tracking-tight">{i.rank}</TableCell>
            <TableCell>
              <div>{i.title}</div>
              {!compact && <div className="text-xs text-muted-foreground">Rule: {i.rule}</div>}
            </TableCell>
            {!compact && <TableCell><StatusBadge status="unknown" label={KIND_LABEL[i.kind] ?? i.kind} /></TableCell>}
            <TableCell>{name(i.brand_id)}</TableCell>
            <TableCell className="text-right font-mono tabular-nums tracking-tight">
              {i.impact_score === null
                ? <span className="text-muted-foreground" title="Impact cannot be computed from the available inputs">{UNAVAILABLE}</span>
                : formatMoney(i.impact_score)}
            </TableCell>
            {!compact && <TableCell className="text-muted-foreground">{i.impact_basis}</TableCell>}
            {!compact && <TableCell className="font-mono tabular-nums tracking-tight">{i.period_start} to {i.period_end}</TableCell>}
            <TableCell>
              <button type="button" className="text-sm underline decoration-dotted underline-offset-2 hover:decoration-solid" onClick={() => open(i.evidence_url, i.title)}>
                View
              </button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Ranked top-N strip (items already ranked by the API; sliced only). */
export function NeedsAttentionStrip({ limit = 5 }: { limit?: number }) {
  const q = useAttention();
  return (
    <QueryState q={q}>
      {q.data && <AttentionTable items={q.data.items.slice(0, limit)} compact />}
    </QueryState>
  );
}
