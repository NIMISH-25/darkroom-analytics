import { HATCH_ID } from "@/lib/chart-theme";

/** Pattern content; usable inside a Recharts <defs> too. Fill missing/stale regions with fill="url(#missing-data-hatch)". */
export function HatchPattern() {
  return (
    <pattern id={HATCH_ID} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <rect width="6" height="6" fill="transparent" />
      <line x1="0" y1="0" x2="0" y2="6" stroke="hsl(var(--muted-foreground))" strokeOpacity="0.55" strokeWidth="2" />
    </pattern>
  );
}

/** Hidden SVG defining #missing-data-hatch once for the whole document (rendered by AppShell). */
export function HatchDefs() {
  return (
    <svg aria-hidden width="0" height="0" style={{ position: "absolute" }}>
      <defs>
        <HatchPattern />
      </defs>
    </svg>
  );
}
