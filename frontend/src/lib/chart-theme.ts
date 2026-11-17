/** Shared chart theme: high-contrast tokens from docs/api-contract-amendment-3.md section 6 (>= 3.4:1 on white and on #18181B). */
export const HATCH_ID = "missing-data-hatch";
export const HATCH_FILL = `url(#${HATCH_ID})`;

/** Default line width; actual lines are solid with visible dots. */
export const STROKE_WIDTH = 2.5;
export const DOT_RADIUS = 3;

export const CHART_TOKENS = {
  actual: "#2563EB", // solid, strokeWidth 2.5, visible dots
  projection: "#C2410C", // dashed
  target: "#71717A", // dotted
  grossGmv: "#0072B2",
  attributedGmv: "#009E73",
  refunds: "#B5578F",
  netSales: "#8B5CF6",
  expectedPosts: "#C2410C", // dashed
  actualPosts: "#2563EB",
  statusOk: "#15803D",
  statusWarn: "#A16207", // warn / stale
  statusError: "#DC2626",
  statusUnknown: "#71717A", // always with the hatch
} as const;

export const DASH = { projection: "6 4", target: "2 4", expectedPosts: "6 4" } as const;

/** Backwards-compatible aliases used by existing chart components. */
export const CHART_COLORS = {
  primary: CHART_TOKENS.actual,
  secondary: CHART_TOKENS.projection,
  positive: CHART_TOKENS.statusOk,
  warning: CHART_TOKENS.statusWarn,
  negative: CHART_TOKENS.statusError,
  grid: "hsl(var(--border))",
  axis: "hsl(var(--muted-foreground))",
} as const;

export const SERIES_COLORS = [
  CHART_TOKENS.actual, CHART_TOKENS.projection, CHART_TOKENS.attributedGmv, CHART_TOKENS.netSales, CHART_TOKENS.refunds,
];

export const STATUS_COLORS: Record<string, string> = {
  current: CHART_TOKENS.statusOk,
  forecast: CHART_TOKENS.projection,
  partial: CHART_TOKENS.statusWarn,
  stale: CHART_TOKENS.statusWarn,
  unavailable: CHART_TOKENS.statusUnknown,
};

/** Point status -> short tooltip label. */
export const POINT_STATUS_LABEL: Record<string, string> = {
  current: "Current",
  partial: "Incomplete",
  stale: "Stale",
  unavailable: "Missing",
  forecast: "Forecast",
};

/** Points with these statuses are drawn as null with the hatched overlay. */
export const HATCHED_STATUSES = ["stale", "unavailable", "partial"] as const;
export const isHatched = (status: string) => (HATCHED_STATUSES as readonly string[]).includes(status);

export const CHART_MARGIN = { top: 8, right: 8, bottom: 0, left: 0 };
