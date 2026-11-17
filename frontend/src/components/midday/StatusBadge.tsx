import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type Tone = "emerald" | "amber" | "orange" | "rose" | "zinc";

const TONES: Record<string, { tone: Tone; label?: string }> = {
  current: { tone: "emerald" },
  converted: { tone: "emerald" },
  on_track: { tone: "emerald", label: "on track" },
  stale: { tone: "amber" },
  pending: { tone: "amber" },
  at_risk: { tone: "amber", label: "at risk" },
  partial: { tone: "orange", label: "incomplete" },
  incomplete: { tone: "orange" },
  suspect: { tone: "orange" },
  unavailable: { tone: "rose", label: "missing" },
  missing: { tone: "rose" },
  failed: { tone: "rose" },
  off_track: { tone: "rose", label: "off track" },
  no_video: { tone: "rose", label: "no video" },
  unknown: { tone: "zinc" },
  unassigned: { tone: "zinc" },
  in_transit: { tone: "zinc", label: "in transit" },
  forecast: { tone: "zinc" },
};

/** Coverage / sample / pace state badge. `status` is any API status string; unknown strings render zinc. */
export function StatusBadge({ status, label, className, title }: { status: string; label?: string; className?: string; title?: string }) {
  const t = TONES[status] ?? { tone: "zinc" as Tone };
  return (
    <Badge variant={t.tone} className={cn(className)} title={title}>
      {label ?? t.label ?? status.replace(/_/g, " ")}
    </Badge>
  );
}

/** Goal basis (gross / net ...) badge: neutral, never a status color. */
export function GoalBasisBadge({ basis, className }: { basis: string | null | undefined; className?: string }) {
  if (!basis) return null;
  return <Badge variant="default" className={cn("text-muted-foreground", className)}>basis: {basis}</Badge>;
}
