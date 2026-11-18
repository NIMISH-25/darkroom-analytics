"use client";
import { useCallback, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";

/** Loading / error wrapper for a react-query result. */
export function QueryState({ q, children, rows = 3 }: {
  q: { isLoading: boolean; isError: boolean; error: unknown; data: unknown };
  children: ReactNode;
  rows?: number;
}) {
  if (q.isError) {
    const e = q.error;
    return (
      <div role="alert" className="border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-600 dark:text-rose-400">
        Could not load data: {e instanceof ApiError ? e.message : String(e)}
      </div>
    );
  }
  if (q.isLoading || q.data === undefined) {
    return <div className="space-y-2" aria-busy="true">{Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-16 w-full" />)}</div>;
  }
  return <>{children}</>;
}

/** URL-synced query parameters (replace, no scroll). Empty/undefined value removes the key. */
export function useUrlParams() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const set = useCallback((patch: Record<string, string | null | undefined>) => {
    const p = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === undefined || v === "") p.delete(k); else p.set(k, v);
    }
    const s = p.toString();
    router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false });
  }, [params, pathname, router]);
  return { params, get: (k: string) => params.get(k) ?? "", set };
}

export function Section({ title, description, actions, children, className }: {
  title: string; description?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={cn("border border-border bg-card", className)}>
      <header className="flex items-start justify-between gap-4 border-b border-border px-4 py-3">
        <div>
          <h2 className="text-sm font-medium">{title}</h2>
          {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
        </div>
        {actions}
      </header>
      <div>{children}</div>
    </section>
  );
}

export function Select({ label, value, onChange, options, allLabel = "All" }: {
  label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; allLabel?: string;
}) {
  return (
    <label className="flex items-center gap-2 text-sm text-muted-foreground">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 rounded-none border border-border bg-background px-2 text-sm text-foreground focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring"
      >
        <option value="">{allLabel}</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

export const Mono = ({ children, className }: { children: ReactNode; className?: string }) => (
  <span className={cn("font-mono tabular-nums tracking-tight", className)}>{children}</span>
);
