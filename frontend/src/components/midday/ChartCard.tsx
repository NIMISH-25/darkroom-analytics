import type { ReactNode } from "react";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { StatusBadge } from "./StatusBadge";

export interface ChartInfo { what: string; how: string; decision: string }

export interface ChartCardProps {
  title: string;
  description?: ReactNode;
  /** Right-aligned legend slot in the header. */
  legend?: ReactNode;
  /** (i) popover copy: what the chart shows, how to read it, what decision it helps with. */
  info?: ChartInfo;
  /** Envelope-level status shown in the footer. */
  status?: string | null;
  statusReason?: string | null;
  coverageThrough?: string | null;
  dataRevision?: number | null;
  className?: string;
  children: ReactNode;
}

function InfoButton({ info, title }: { info: ChartInfo; title: string }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" aria-label={`About ${title}`} className="flex h-8 w-8 shrink-0 items-center justify-center border border-border text-muted-foreground hover:bg-accent hover:text-foreground">
          <Info className="h-4 w-4" />
        </button>
      </PopoverTrigger>
      <PopoverContent>
        <dl className="space-y-3">
          <div><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">What it shows</dt><dd className="mt-1">{info.what}</dd></div>
          <div><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">How to read it</dt><dd className="mt-1">{info.how}</dd></div>
          <div><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Decision it helps with</dt><dd className="mt-1">{info.decision}</dd></div>
        </dl>
      </PopoverContent>
    </Popover>
  );
}

/** Hairline chart container: header (title, description, legend, (i) info) / body / footer (status, coverage, revision). */
export function ChartCard({ title, description, legend, info, status, statusReason, coverageThrough, dataRevision, className, children }: ChartCardProps) {
  return (
    <section className={cn("flex flex-col border border-border bg-card", className)}>
      <header className="flex items-start justify-between gap-4 border-b border-border px-4 py-3">
        <div>
          <h3 className="text-base font-medium">{title}</h3>
          {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
        </div>
        <div className="flex items-start gap-3">
          {legend && <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">{legend}</div>}
          {info && <InfoButton info={info} title={title} />}
        </div>
      </header>
      <div className="flex-1 p-4">{children}</div>
      <footer className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-2 text-xs text-muted-foreground">
        {status && <StatusBadge status={status} />}
        {statusReason && <span>{statusReason}</span>}
        <span className="ml-auto flex items-center gap-3 font-mono tabular-nums tracking-tight">
          {coverageThrough !== undefined && <span>coverage through {coverageThrough ?? "UNAVAILABLE"}</span>}
          {dataRevision !== undefined && dataRevision !== null && <span>rev {dataRevision}</span>}
        </span>
      </footer>
    </section>
  );
}
