"use client";
import { useMemo, useState } from "react";
import { useMutation, useQueries } from "@tanstack/react-query";
import { flexRender } from "@tanstack/react-table";
import { getCoreRowModel, getSortedRowModel, useLegacyTable } from "@tanstack/react-table/legacy";
import type { SortingState } from "@tanstack/react-table";
import type { LegacyColumnDef } from "@tanstack/react-table/legacy";
type ColumnDef<T extends object> = LegacyColumnDef<T>;
import { ArrowDown, ArrowUp } from "lucide-react";
import { apiGet } from "@/lib/api";
import { useAddCreatorNote, useCreatorNotes, useCreators, useMeta, useRevision } from "@/lib/hooks";
import type { CreatorItem, Creators, MV, SuggestedActionKind } from "@/lib/types";
import { MetricValue } from "@/components/midday/MetricValue";
import { StatusBadge } from "@/components/midday/StatusBadge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { UNAVAILABLE } from "@/lib/format";
import { QueryState, Select, useUrlParams } from "./common";

export type CreatorRow = CreatorItem & { brand_id: string; brand_name: string };

const ACTIONS: SuggestedActionKind[] = ["review", "nudge", "upgrade", "rebook", "watch"];
const ACTION_TONE: Record<SuggestedActionKind, string> = {
  review: "orange", nudge: "amber", upgrade: "emerald", rebook: "zinc", watch: "zinc",
};

/** Roster for every brand: one query per brand (batched), tagged with brand. */
export function useAllCreators() {
  const meta = useMeta().data;
  const revision = useRevision();
  const brands = meta?.brands ?? [];
  const results = useQueries({
    queries: brands.map((b) => ({
      queryKey: ["api", `/api/v1/brands/${b.brand_id}/creators`, revision],
      queryFn: () => apiGet<Creators>(`/api/v1/brands/${b.brand_id}/creators`),
      enabled: revision !== undefined,
      staleTime: Infinity,
    })),
  });
  const rows: CreatorRow[] = results.flatMap((r, i) => (r.data?.items ?? []).map((c) => ({ ...c, brand_id: brands[i].brand_id, brand_name: brands[i].name })));
  const contractTypes = Array.from(new Set(results.flatMap((r) => r.data?.contract_types ?? [])));
  return {
    rows, contractTypes,
    isLoading: !meta || results.some((r) => r.isLoading),
    isError: results.some((r) => r.isError),
    error: results.find((r) => r.error)?.error,
    data: meta ? rows : undefined,
  };
}

export function useBrandCreators(brandId: string) {
  const q = useCreators(brandId);
  const meta = useMeta().data;
  const name = meta?.brands.find((b) => b.brand_id === brandId)?.name ?? brandId;
  const rows: CreatorRow[] = (q.data?.items ?? []).map((c) => ({ ...c, brand_id: brandId, brand_name: name }));
  return { rows, contractTypes: q.data?.contract_types ?? [], isLoading: q.isLoading, isError: q.isError, error: q.error, data: q.data };
}

function SuggestedActionBadge({ a }: { a: CreatorItem["suggested_action"] }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="inline-flex cursor-help items-center gap-1">
          <StatusBadge status={ACTION_TONE[a.action] === "zinc" ? "unknown" : ACTION_TONE[a.action] === "emerald" ? "current" : ACTION_TONE[a.action] === "amber" ? "stale" : "incomplete"} label={a.action} />
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">
        <p className="font-medium">Rule</p>
        <p>{a.rule}</p>
        {a.status_reason && <p className="mt-1 text-muted-foreground">{a.status_reason}</p>}
      </TooltipContent>
    </Tooltip>
  );
}

/** Sort key only (not a metric): numeric value of an MV, undefined when unknown so it sorts last. */
const key = (mv: MV) => (mv.value === null ? undefined : Number(mv.value));

function buildColumns(showBrand: boolean): ColumnDef<CreatorRow>[] {
  const mvCol = (id: string, header: string, pick: (r: CreatorRow) => MV): ColumnDef<CreatorRow> => ({
    id, header, accessorFn: (r) => key(pick(r)), sortUndefined: "last",
    cell: ({ row }) => <div className="text-right"><MetricValue mv={pick(row.original)} label={`${header} · ${row.original.handle}`} showReason={false} /></div>,
    meta: { align: "right" },
  } as ColumnDef<CreatorRow>);
  return [
    { id: "handle", header: "Creator", accessorFn: (r) => r.handle, cell: ({ row }) => <span className="font-medium">{row.original.handle}</span> },
    ...(showBrand ? [{ id: "brand", header: "Brand", accessorFn: (r: CreatorRow) => r.brand_name } as ColumnDef<CreatorRow>] : []),
    { id: "contract", header: "Contract", accessorFn: (r) => r.contract_type },
    mvCol("videos", "Videos", (r) => r.videos),
    mvCol("gmv", "GMV", (r) => r.gmv),
    mvCol("refunds", "Refunds", (r) => r.refunds),
    mvCol("retainer", "Retainer", (r) => r.retainer_cost),
    mvCol("commission", "Commission", (r) => r.commission_cost),
    mvCol("sample_cost", "Sample cost", (r) => r.sample_cost),
    mvCol("sales_after_costs", "Sales after costs", (r) => r.sales_after_costs),
    { id: "last_post", header: "Last post", accessorFn: (r) => r.last_post_date ?? undefined, sortUndefined: "last",
      cell: ({ row }) => <span className="font-mono tabular-nums tracking-tight">{row.original.last_post_date ?? UNAVAILABLE}</span> } as ColumnDef<CreatorRow>,
    { id: "action", header: "Suggested action", accessorFn: (r) => r.suggested_action.action, cell: ({ row }) => <SuggestedActionBadge a={row.original.suggested_action} /> },
  ];
}

export function CreatorsTable({ rows, contractTypes, showBrand, brandOptions }: {
  rows: CreatorRow[]; contractTypes: string[]; showBrand: boolean; brandOptions?: { value: string; label: string }[];
}) {
  const { get, set } = useUrlParams();
  const [openRow, setOpenRow] = useState<CreatorRow | null>(null);
  const q = get("q").toLowerCase(), brand = get("brand"), contract = get("contract"), action = get("action");
  const sorting: SortingState = get("sort") ? [{ id: get("sort"), desc: get("order") !== "asc" }] : [];

  const data = useMemo(() => rows.filter((r) =>
    (!q || r.handle.toLowerCase().includes(q) || r.creator_id.toLowerCase().includes(q)) &&
    (!brand || r.brand_id === brand) && (!contract || r.contract_type === contract) && (!action || r.suggested_action.action === action),
  ), [rows, q, brand, contract, action]);
  const columns = useMemo(() => buildColumns(showBrand), [showBrand]);

  const table = useLegacyTable<CreatorRow>({
    data, columns, state: { sorting },
    onSortingChange: (u: SortingState | ((o: SortingState) => SortingState)) => {
      const next = typeof u === "function" ? u(sorting) : u;
      set({ sort: next[0]?.id ?? null, order: next[0] ? (next[0].desc ? "desc" : "asc") : null });
    },
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(),
    enableSortingRemoval: true,
  } as never);

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
        <input type="search" aria-label="Search creators" placeholder="Search handle" value={get("q")}
          onChange={(e) => set({ q: e.target.value })}
          className="h-8 w-44 rounded-none border border-border bg-background px-2 text-sm focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring" />
        {showBrand && brandOptions && <Select label="Brand" value={brand} onChange={(v) => set({ brand: v })} options={brandOptions} />}
        <Select label="Contract" value={contract} onChange={(v) => set({ contract: v })} options={contractTypes.map((c) => ({ value: c, label: c }))} />
        <Select label="Suggested action" value={action} onChange={(v) => set({ action: v })} options={ACTIONS.map((a) => ({ value: a, label: a }))} />
        <span className="ml-auto font-mono text-xs tabular-nums text-muted-foreground">{data.length} of {rows.length} creators</span>
      </div>
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((hg) => (
            <TableRow key={hg.id}>
              {hg.headers.map((h) => {
                const s = h.column.getIsSorted();
                const numeric = (h.column.columnDef as { meta?: { align?: string } }).meta?.align === "right";
                return (
                  <TableHead key={h.id} className={numeric ? "text-right" : undefined} aria-sort={s === "asc" ? "ascending" : s === "desc" ? "descending" : "none"}>
                    <button type="button" onClick={h.column.getToggleSortingHandler()} className="inline-flex items-center gap-1 uppercase hover:text-foreground">
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {s === "asc" ? <ArrowUp className="h-3 w-3" /> : s === "desc" ? <ArrowDown className="h-3 w-3" /> : null}
                    </button>
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((r) => (
            <TableRow key={`${r.original.brand_id}-${r.original.creator_id}`} tabIndex={0} className="cursor-pointer"
              onClick={() => setOpenRow(r.original)}
              onKeyDown={(e) => { if (e.key === "Enter") setOpenRow(r.original); }}>
              {r.getVisibleCells().map((c) => <TableCell key={c.id}>{flexRender(c.column.columnDef.cell, c.getContext())}</TableCell>)}
            </TableRow>
          ))}
          {data.length === 0 && <TableRow><TableCell colSpan={columns.length} className="text-muted-foreground">No creators match the filters.</TableCell></TableRow>}
        </TableBody>
      </Table>
      <CreatorSheet row={openRow} onClose={() => setOpenRow(null)} />
    </div>
  );
}

function Notes({ brandId, creatorId }: { brandId: string; creatorId: string }) {
  const notes = useCreatorNotes(brandId, creatorId);
  const add = useAddCreatorNote(brandId, creatorId);
  const [text, setText] = useState("");
  const trimmed = text.trim();
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!trimmed) return;
    add.mutate(trimmed, { onSuccess: () => setText("") });
  };
  return (
    <section className="space-y-2 border-t border-border pt-3">
      <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Operational notes</h4>
      <form onSubmit={submit} className="space-y-2">
        <label className="sr-only" htmlFor="note-body">Add a note</label>
        <textarea id="note-body" value={text} maxLength={2000} rows={3} onChange={(e) => setText(e.target.value)}
          placeholder="Add an operational note (plain text, up to 2000 characters)"
          className="w-full rounded-none border border-border bg-background p-2 text-sm focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring" />
        <div className="flex items-center gap-3">
          <Button type="submit" size="sm" disabled={!trimmed || add.isPending}>{add.isPending ? "Saving..." : "Add note"}</Button>
          {add.isError && <span role="alert" className="text-sm text-rose-500">Could not save note: {String((add.error as Error)?.message ?? add.error)}</span>}
          <span className="ml-auto font-mono text-xs tabular-nums text-muted-foreground">{text.length}/2000</span>
        </div>
      </form>
      {notes.isLoading && <p className="text-sm text-muted-foreground">Loading notes...</p>}
      {notes.isError && <p className="text-sm text-rose-500">Could not load notes.</p>}
      {notes.data && (notes.data.items.length === 0
        ? <p className="text-sm text-muted-foreground">No notes yet.</p>
        : (
          <ul className="divide-y divide-border border border-border">
            {notes.data.items.map((n) => (
              <li key={n.note_id} className="p-2 text-sm">
                <div className="font-mono text-xs tabular-nums tracking-tight text-muted-foreground">{n.author} · {n.created_at}</div>
                <p className="mt-1 whitespace-pre-wrap">{n.body}</p>
              </li>
            ))}
          </ul>
        ))}
    </section>
  );
}

export function CreatorSheet({ row, onClose }: { row: CreatorRow | null; onClose: () => void }) {
  return (
    <Sheet open={row !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent>
        {row && (
          <>
            <SheetHeader>
              <SheetTitle>{row.handle}</SheetTitle>
              <SheetDescription>{row.brand_name} · {row.contract_type} · coverage <StatusBadge status={row.coverage_status} /></SheetDescription>
            </SheetHeader>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
              {([
                ["Videos", row.videos], ["GMV", row.gmv], ["Refunds", row.refunds], ["Net sales", row.net_sales],
                ["Retainer", row.retainer_cost], ["Commission", row.commission_cost], ["Sample cost", row.sample_cost],
                ["Sales after costs", row.sales_after_costs], ["Unresolved GMV", row.unresolved_gmv],
              ] as [string, MV][]).map(([l, mv]) => (
                <div key={l} className="flex items-start justify-between gap-2 border-b border-border pb-1">
                  <dt className="text-muted-foreground">{l}</dt>
                  <dd><MetricValue mv={mv} label={`${l} · ${row.handle}`} /></dd>
                </div>
              ))}
              <div className="flex justify-between gap-2 border-b border-border pb-1">
                <dt className="text-muted-foreground">Last post</dt>
                <dd className="font-mono tabular-nums tracking-tight">{row.last_post_date ?? UNAVAILABLE}</dd>
              </div>
            </dl>
            <div className="space-y-1 border-t border-border pt-3 text-sm">
              <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Suggested action</h4>
              <SuggestedActionBadge a={row.suggested_action} />
              <p className="text-muted-foreground">Rule: {row.suggested_action.rule}</p>
              {row.suggested_action.status_reason && <p className="text-muted-foreground">{row.suggested_action.status_reason}</p>}
            </div>
            <Notes brandId={row.brand_id} creatorId={row.creator_id} />
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

export { QueryState };
