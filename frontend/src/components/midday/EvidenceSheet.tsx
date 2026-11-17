"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, fetchEvidence } from "@/lib/api";
import { formatMV, formatValue, formatMoney, UNAVAILABLE } from "@/lib/format";
import type { Evidence } from "@/lib/types";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge } from "./StatusBadge";

interface Ctx { open: (evidenceUrl: string, title?: string) => void; close: () => void }
const EvidenceCtx = createContext<Ctx>({ open: () => {}, close: () => {} });
/** Open the right-hand evidence sheet for any MetricValue / chart point: `open(mv.evidence_url, "label")`. */
export const useEvidenceSheet = () => useContext(EvidenceCtx);

const PAGE = 100;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-border pt-3">
      <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h4>
      {children}
    </section>
  );
}

export function EvidenceSheetProvider({ children }: { children: ReactNode }) {
  const [url, setUrl] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [head, setHead] = useState<Evidence | null>(null);
  const [records, setRecords] = useState<Evidence["records"]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const open = useCallback((u: string, t?: string) => { setUrl(u); setTitle(t ?? ""); }, []);
  const close = useCallback(() => setUrl(null), []);

  useEffect(() => {
    if (!url) return;
    let alive = true;
    setLoading(true); setError(null); setHead(null); setRecords([]); setNext(null);
    fetchEvidence<Evidence>(url, 0, PAGE)
      .then((d) => { if (!alive) return; setHead(d); setRecords(d.records); setNext(d.next_offset); })
      .catch((e) => alive && setError(e instanceof ApiError ? `${e.message}` : String(e)))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [url]);

  async function more() {
    if (!url || next === null) return;
    setLoading(true);
    try {
      const d = await fetchEvidence<Evidence>(url, next, PAGE);
      setRecords((r) => [...r, ...d.records]);
      setNext(d.next_offset);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setLoading(false); }
  }

  const ctx = useMemo(() => ({ open, close }), [open, close]);
  const ev = head;
  return (
    <EvidenceCtx.Provider value={ctx}>
      {children}
      <Sheet open={url !== null} onOpenChange={(o) => !o && close()}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>{ev?.label || title || "Evidence"}</SheetTitle>
            <SheetDescription>Where this number comes from. Pinned to the data revision in the link.</SheetDescription>
          </SheetHeader>
          {loading && !ev && <div className="space-y-2"><Skeleton className="h-8 w-1/2" /><Skeleton className="h-24 w-full" /><Skeleton className="h-40 w-full" /></div>}
          {error && <p className="text-xs text-rose-500">{error}</p>}
          {ev && (
            <div className="space-y-4 text-sm">
              {ev.explainer && (
                <section className="space-y-2 border border-border bg-muted/40 p-4">
                  <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">What This Number Means</h4>
                  <p>{ev.explainer.what_it_means}</p>
                  <p><span className="font-medium">Why it matters. </span>{ev.explainer.why_it_matters}</p>
                  <p><span className="font-medium">How it is calculated. </span>{ev.explainer.how_calculated}</p>
                  <p><span className="font-medium">What the rows prove. </span>{ev.explainer.what_rows_prove}</p>
                </section>
              )}
              <div className="flex items-center gap-3">
                <span className="font-mono text-3xl tabular-nums tracking-tight">{formatMV(ev.result)}</span>
                <StatusBadge status={ev.result.status} />
              </div>
              {ev.result.status_reason && <p className="text-muted-foreground">{ev.result.status_reason}</p>}
              <p className="font-mono tabular-nums tracking-tight text-muted-foreground">
                {ev.period_start} to {ev.period_end} ({ev.timezone}) · def {ev.definition_version}
              </p>
              <Section title="Definition"><p>{ev.definition}</p></Section>
              <Section title={`Formula (${ev.calculation.kind})`}>
                <code className="block border border-border bg-muted px-2 py-1.5 font-mono">{ev.calculation.formula}</code>
                {ev.calculation.inputs.length > 0 && (
                  <Table className="mt-2">
                    <TableHeader><TableRow><TableHead>Input</TableHead><TableHead className="text-right">Value</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {ev.calculation.inputs.map((i, k) => (
                        <TableRow key={k}><TableCell>{i.label}</TableCell><TableCell className="text-right font-mono tabular-nums tracking-tight">{formatValue(i.value, i.unit)}</TableCell></TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </Section>
              <Section title="Exclusions">
                {ev.exclusions.length === 0 ? <p className="text-muted-foreground">None</p> : (
                  <Table>
                    <TableHeader><TableRow><TableHead>Reason</TableHead><TableHead className="text-right">Count</TableHead><TableHead className="text-right">Amount</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {ev.exclusions.map((x, k) => (
                        <TableRow key={k}>
                          <TableCell>{x.reason}</TableCell>
                          <TableCell className="text-right font-mono tabular-nums tracking-tight">{x.count}</TableCell>
                          <TableCell className="text-right font-mono tabular-nums tracking-tight">{x.amount === null ? UNAVAILABLE : formatMoney(x.amount)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </Section>
              <Section title="Warnings">
                {ev.warnings.length === 0 ? <p className="text-muted-foreground">None</p> : (
                  <ul className="list-disc space-y-1 pl-4 text-amber-600 dark:text-amber-400">{ev.warnings.map((w, k) => <li key={k}>{w}</li>)}</ul>
                )}
              </Section>
              <Section title={`Records (${records.length} of ${ev.total_count})`}>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Source file</TableHead><TableHead>Locator</TableHead><TableHead>Incl.</TableHead>
                      {ev.columns.map((c) => <TableHead key={c}>{c}</TableHead>)}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {records.map((r, k) => (
                      <TableRow key={k} className={r.included ? "" : "text-muted-foreground line-through"}>
                        <TableCell className="font-mono">{r.source_file}</TableCell>
                        <TableCell className="font-mono tabular-nums tracking-tight">{r.source_locator}</TableCell>
                        <TableCell>{r.included ? "yes" : "no"}</TableCell>
                        {ev.columns.map((c) => (
                          <TableCell key={c} className="font-mono tabular-nums tracking-tight">
                            {r.values[c] === null || r.values[c] === undefined ? UNAVAILABLE : String(r.values[c])}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {next !== null && (
                  <Button variant="outline" size="sm" className="mt-2" disabled={loading} onClick={more}>
                    {loading ? "Loading..." : "Load more"}
                  </Button>
                )}
              </Section>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </EvidenceCtx.Provider>
  );
}
