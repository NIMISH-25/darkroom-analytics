import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type Tone = "emerald" | "amber" | "orange" | "rose" | "zinc";

const TONES: Record<string, { tone: Tone; label?: string }> = {
  current: { tone: "emerald", label: "complete" },
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

/**
 * Coverage / sample / pace state badge. `status` is any API status string; unknown strings render zinc.
 * `reason` (plain text, e.g. status_reason + data_note) makes the badge focusable and shows it in a hover and keyboard-focus tooltip.
 * `title` is accepted as a legacy alias for `reason`.
 */
export function StatusBadge({ status, label, className, reason, title }: { status: string; label?: string; className?: string; reason?: string | null; title?: string }) {
  const t = TONES[status] ?? { tone: "zinc" as Tone };
  const badge = (
    <Badge variant={t.tone} className={cn(className)}>
      {label ?? t.label ?? status.replace(/_/g, " ")}
    </Badge>
  );
  const text = reason || title;
  if (!text) return badge;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="inline-flex cursor-help focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring">{badge}</span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-sm">{text}</TooltipContent>
    </Tooltip>
  );
}

/** Join the plain reason and data note of a metric value into one tooltip text. */
export function reasonText(...parts: (string | null | undefined)[]): string | undefined {
  const t = parts.filter(Boolean).join(" ");
  return t || undefined;
}

/** Goal basis (gross / net ...) badge: neutral, never a status color. */
export function GoalBasisBadge({ basis, className }: { basis: string | null | undefined; className?: string }) {
  if (!basis) return null;
  return <Badge variant="default" className={cn("text-muted-foreground", className)}>basis: {basis}</Badge>;
}
