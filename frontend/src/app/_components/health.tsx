"use client";
import { StatusBadge } from "@/components/midday/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDataHealth, useMeta } from "@/lib/hooks";
import type { DataHealth } from "@/lib/types";
import { QueryState, Section } from "./common";
import type { PlainFile } from "./ext";

const mono = "font-mono tabular-nums tracking-tight";
const SHARED_LABEL = "Shared Cross-Brand Source";

/** Amendment 3 fields (scope, source_label, counts) read defensively on top of the foundation type. */
type Scoped = { scope?: "brand" | "shared"; brand_id?: string | null; source_label?: string | null };
type Source = DataHealth["sources"][number] & Scoped;
type Failed = DataHealth["failed_files"][number] & Scoped;
type Counts = { brand_failed: number; shared_failed: number; open_issues: number; rows_excluded?: number };
const countsOf = (d: DataHealth) => (d as DataHealth & { counts?: Counts }).counts;

function SharedBadge({ label }: { label?: string | null }) {
  return <Badge variant="default" className="text-muted-foreground">{label ?? SHARED_LABEL}</Badge>;
}

export function FreshnessGrid({ data, brands }: { data: DataHealth; brands: { brand_id: string; name: string }[] }) {
  const all = data.sources as Source[];
  const sources = Array.from(new Set(all.map((s) => s.source)));
  const shared = all.filter((s) => s.scope === "shared");
  const rows = [
    ...brands.map((b) => ({ key: b.brand_id, name: b.name, shared: false, items: all.filter((x) => x.scope !== "shared" && x.brand_id === b.brand_id) })),
    ...(shared.length ? [{ key: "__shared", name: SHARED_LABEL, shared: true, items: shared }] : []),
  ];
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Brand</TableHead>
          {sources.map((s) => <TableHead key={s}>{s}</TableHead>)}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.key}>
            <TableCell className="font-medium">{r.shared ? <SharedBadge /> : r.name}</TableCell>
            {sources.map((s) => {
              const c = r.items.find((x) => x.source === s);
              return (
                <TableCell key={s} className="align-top">
                  {c ? (
                    <div className="space-y-1">
                      <StatusBadge status={c.status} />
                      <div className={`${mono} text-xs text-muted-foreground`}>through {c.coverage_through ?? "no data yet"}</div>
                      <div className={`${mono} text-xs text-muted-foreground`}>ingested {c.last_ingested_at ?? "not yet"}</div>
                      {c.message && <div className="max-w-[28ch] text-xs text-muted-foreground">{c.message}</div>}
                    </div>
                  ) : <span className="text-muted-foreground">-</span>}
                </TableCell>
              );
            })}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function Runs({ data }: { data: DataHealth }) {
  return (
    <Table>
      <TableHeader><TableRow><TableHead>Run</TableHead><TableHead>Started</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Files failed</TableHead></TableRow></TableHeader>
      <TableBody>
        {data.runs.map((r) => (
          <TableRow key={r.run_id}>
            <TableCell className={mono}>{r.run_id}</TableCell>
            <TableCell className={mono}>{r.started_at}</TableCell>
            <TableCell><StatusBadge status={r.status === "succeeded" || r.status === "success" ? "current" : r.status === "failed" ? "failed" : "unknown"} label={r.status} /></TableCell>
            <TableCell className={`${mono} text-right`}>{r.files_failed}</TableCell>
          </TableRow>
        ))}
        {data.runs.length === 0 && <TableRow><TableCell colSpan={4} className="text-muted-foreground">No ingest runs.</TableCell></TableRow>}
      </TableBody>
    </Table>
  );
}

function FailedFiles({ data, brandId, brandName }: { data: DataHealth; brandId?: string; brandName: (id: string) => string }) {
  // Never show another brand's failure: in brand view keep this brand's files and shared ones only.
  const files = (data.failed_files as (Failed & PlainFile)[]).filter((f) => !brandId || f.scope === "shared" || !f.brand_id || f.brand_id === brandId);
  if (files.length === 0) return <p className="p-4 text-sm text-muted-foreground">No files failed to load.</p>;
  return (
    <Table>
      <TableHeader><TableRow><TableHead>Brand</TableHead><TableHead>What happened</TableHead></TableRow></TableHeader>
      <TableBody>
        {files.map((f, i) => (
          <TableRow key={i}>
            <TableCell>{f.scope === "shared" ? <SharedBadge label={f.source_label} /> : f.brand_name ?? (f.brand_id ? brandName(f.brand_id) : "")}</TableCell>
            <TableCell className="text-rose-600 dark:text-rose-400">{f.plain_reason ?? "This file could not be loaded."}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function LeftOut({ data, brandId }: { data: DataHealth; brandId?: string }) {
  const all = ((data.files_with_exclusions ?? []) as unknown as PlainFile[])
    .filter((f) => !brandId || f.scope === "shared" || !f.brand_id || f.brand_id === brandId);
  if (all.length === 0) return <p className="p-4 text-sm text-muted-foreground">No records were left out.</p>;
  return (
    <ul className="divide-y divide-border">
      {all.map((f, i) => {
        const n = f.excluded_rows ?? f.rows_excluded ?? f.count;
        const label = f.plain_file_label ?? f.file_label ?? f.source_label ?? "a file";
        return (
          <li key={i} className="space-y-1 px-4 py-3 text-sm">
            <div>
              {f.brand_name && <span className="font-medium">{f.brand_name}: </span>}
              <span className="font-mono tabular-nums tracking-tight">{n ?? ""}</span> records left out of {label}
            </div>
            {f.plain_reason && <p className="text-muted-foreground">{f.plain_reason}</p>}
          </li>
        );
      })}
    </ul>
  );
}

function Unresolved({ data, brandId, brandName }: { data: DataHealth; brandId?: string; brandName: (id: string) => string }) {
  const items = data.unresolved_identities.filter((u) => !brandId || !u.brand_id || u.brand_id === brandId);
  if (items.length === 0) return <p className="p-4 text-sm text-muted-foreground">No unresolved identities.</p>;
  return (
    <Table>
      <TableHeader><TableRow><TableHead>Brand</TableHead><TableHead>Source</TableHead><TableHead>Raw identifier</TableHead><TableHead className="text-right">Occurrences</TableHead></TableRow></TableHeader>
      <TableBody>
        {items.map((u, i) => (
          <TableRow key={i}><TableCell>{u.brand_id ? brandName(u.brand_id) : SHARED_LABEL}</TableCell><TableCell>{u.source}</TableCell><TableCell className={mono}>{u.raw_identifier}</TableCell><TableCell className={`${mono} text-right`}>{u.occurrences}</TableCell></TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function CountsLine({ c }: { c: Counts }) {
  return (
    <div className="flex flex-wrap gap-6 border border-border bg-card px-4 py-3 text-sm text-muted-foreground" aria-label="Health counts">
      <span>Brand failures <span className={`${mono} text-foreground`}>{c.brand_failed}</span></span>
      <span>Shared failures <span className={`${mono} text-foreground`}>{c.shared_failed}</span></span>
      <span>Open issues <span className={`${mono} text-foreground`}>{c.open_issues}</span></span>
      {c.rows_excluded !== undefined && <span>Records left out <span className={`${mono} text-foreground`}>{c.rows_excluded}</span></span>}
    </div>
  );
}

/** brandId set = that brand's files plus labelled shared trackers; otherwise portfolio. No charts. */
export function HealthSections({ brandId }: { brandId?: string }) {
  const health = useDataHealth(brandId);
  const meta = useMeta();
  const allBrands = meta.data?.brands ?? [];
  const brands = allBrands.filter((b) => !brandId || b.brand_id === brandId);
  const brandName = (id: string) => allBrands.find((b) => b.brand_id === id)?.name ?? id;
  return (
    <QueryState q={health}>
      {health.data && (
        <div className="space-y-4">
          {countsOf(health.data) && <CountsLine c={countsOf(health.data)!} />}
          <Section title="Source freshness and coverage">
            <FreshnessGrid data={health.data} brands={brands} />
          </Section>
          {!brandId && <Section title="Ingest runs"><Runs data={health.data} /></Section>}
          <Section title="Files that failed to load"><FailedFiles data={health.data} brandId={brandId} brandName={brandName} /></Section>
          <Section title="Records left out"><LeftOut data={health.data} brandId={brandId} /></Section>
          <Section title="Unresolved identities"><Unresolved data={health.data} brandId={brandId} brandName={brandName} /></Section>
        </div>
      )}
    </QueryState>
  );
}
