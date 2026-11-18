"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, fetchEvidence } from "@/lib/api";
import { formatMV, NO_DATA } from "@/lib/format";
import type { Evidence } from "@/lib/types";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge, reasonText } from "./StatusBadge";

interface Ctx { open: (evidenceUrl: string, title?: string) => void; close: () => void }
const EvidenceCtx = createContext<Ctx>({ open: () => {}, close: () => {} });
/** Open the right-hand evidence sheet for any MetricValue / chart point: `open(mv.evidence_url, "label")`. */
export const useEvidenceSheet = () => useContext(EvidenceCtx);

const PAGE = 100;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-border pt-3">
      <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h4>
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
  const meaning = ev?.what_this_means ?? ev?.explainer?.what_it_means;
  const why = ev?.why_it_matters ?? ev?.explainer?.why_it_matters;
  const watch = ev?.what_to_watch ?? ev?.explainer?.what_rows_prove;
  const note = reasonText(ev?.incomplete_reason, ev?.data_note);
  const cols = ev?.columns_plain ?? [];
  const rowLabel = (loc: string) => { const m = /(\d+)/.exec(loc); return m ? `Row ${m[1]}` : loc; };
  return (
    <EvidenceCtx.Provider value={ctx}>
      {children}
      <Sheet open={url !== null} onOpenChange={(o) => !o && close()}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>{title || ev?.label || "Evidence"}</SheetTitle>
            <SheetDescription>Where this number comes from.</SheetDescription>
          </SheetHeader>
          {loading && !ev && <div className="space-y-2"><Skeleton className="h-8 w-1/2" /><Skeleton className="h-24 w-full" /><Skeleton className="h-40 w-full" /></div>}
          {error && <p className="text-sm text-rose-500">{error}</p>}
          {ev && (
            <div className="space-y-5 text-sm">
              <div className="flex flex-wrap items-center gap-3">
                <span className="font-mono text-3xl tabular-nums tracking-tight">{formatMV(ev.result)}</span>
                {ev.result.status !== "current" && <StatusBadge status={ev.result.status} reason={reasonText(ev.result.status_reason, ev.result.data_note)} />}
              </div>
              {meaning && <Section title="What this number means"><p>{meaning}</p></Section>}
              {why && <Section title="Why it matters"><p>{why}</p></Section>}
              {watch && <Section title="What to watch"><p>{watch}</p></Section>}
              {note && <p className="border border-amber-500/40 bg-amber-500/10 p-3 text-amber-700 dark:text-amber-400">{note}</p>}
              <Section title="Supporting records">
                {records.length === 0 ? <p className="text-muted-foreground">No supporting records for this number.</p> : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>File</TableHead><TableHead>Where in the file</TableHead><TableHead>Counted</TableHead>
                        {cols.map((c) => <TableHead key={c.key}>{c.label}</TableHead>)}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {records.map((r, k) => (
                        <TableRow key={k} className={r.included ? "" : "text-muted-foreground"}>
                          <TableCell>{r.source_file}</TableCell>
                          <TableCell className="font-mono tabular-nums tracking-tight">{rowLabel(r.source_locator)}</TableCell>
                          <TableCell>{r.included ? "Yes" : "Left out"}</TableCell>
                          {cols.map((c) => (
                            <TableCell key={c.key} className="font-mono tabular-nums tracking-tight">
                              {r.values[c.key] === null || r.values[c.key] === undefined ? NO_DATA : String(r.values[c.key])}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
                {next !== null && (
                  <Button variant="outline" className="mt-3" disabled={loading} onClick={more}>
                    {loading ? "Loading..." : "Show more"}
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
