/* Types for docs/api-contract.md + docs/api-contract-amendment-2.md. Money/decimals are STRINGS; null = unknown. */

export type Status = "current" | "partial" | "stale" | "unavailable";
export type PointStatus = Status | "forecast";
export type Unit = "USD" | "count" | "ratio" | "days" | "USD_per_day" | "count_per_day";

export interface MV {
  /** Plain note when figures are floors because rows were left out; else null. */
  data_note?: string | null;
  metric_key: string;
  value: string | number | null;
  unit: Unit;
  as_of: string;
  coverage_through: string | null;
  status: Status;
  status_reason: string | null;
  evidence_url: string;
}
/** Some diagnostics fields may be a full MV or a bare value; the formatter accepts both. */
export type Val = MV | string | number | null;

export interface Meta {
  default_month: string;
  default_cutoff: string;
  months: string[];
  brands: { brand_id: string; name: string; timezone: string }[];
  data_revision: number;
}

export type PaceStatus = "on_track" | "at_risk" | "off_track" | "unknown";
export interface Goal {
  goal_id: string;
  label: string;
  definition: string;
  scope: string;
  basis: string;
  target: MV;
  actual: MV;
  projection: MV;
  required_pace: MV | null;
  /** actual/target ratio computed by the API (capped 1.5); null value when unknown. */
  progress?: MV | null;
  /** false -> hide the required-pace row entirely (distinct-count goals, goals without a target). */
  required_pace_applicable?: boolean;
  /** Plain reason when applicable but the value is null. */
  required_pace_reason?: string | null;
  pace_status: PaceStatus;
  reasoning: string;
}
export interface Overview {
  data_revision: number;
  brands: { brand_id: string; name: string; goals: Goal[] }[];
}

export type SuggestedActionKind = "review" | "nudge" | "upgrade" | "rebook" | "watch";
export interface SuggestedAction {
  action: SuggestedActionKind;
  rule: string;
  status: Status;
  status_reason: string | null;
}

export interface CreatorItem {
  creator_id: string;
  handle: string;
  contract_type: string;
  last_post_date: string | null;
  coverage_status: Status;
  videos: MV;
  gmv: MV;
  refunds: MV;
  net_sales: MV;
  retainer_cost: MV;
  commission_cost: MV;
  sample_cost: MV;
  sales_after_costs: MV;
  unresolved_gmv: MV;
  suggested_action: SuggestedAction;
}
export interface Creators {
  data_revision: number;
  contract_types: string[];
  items: CreatorItem[];
}

export interface CreatorNote {
  note_id: string | number;
  brand_id: string;
  creator_id: string;
  author: string;
  body: string;
  created_at: string;
}
export interface CreatorNotes {
  items: CreatorNote[];
  total_count: number;
}

export type SampleStatus = "in_transit" | "pending" | "matched" | "no_video" | "unknown";
export interface SampleItem {
  sample_id: string;
  creator_id: string;
  handle: string;
  product_sku: string;
  sent_date: string;
  delivered_date: string | null;
  status: SampleStatus;
  video_id: string | null;
  delivery_to_video_days: number | null;
  evidence_url: string;
}
export interface Samples {
  data_revision: number;
  counts: { sent: MV; delivered: MV; matched: MV; pending: MV; no_video: MV; unknown: MV; conversion_rate: MV };
  items: SampleItem[];
}

export type HealthScope = "brand" | "shared";
export interface DataHealth {
  data_revision: number;
  counts?: { brand_failed: number; shared_failed: number; open_issues: number; rows_excluded?: number };
  files_with_exclusions?: { run_id?: string; file_name: string; brand_id?: string | null; brand_name?: string | null; plain_reason: string; rows_excluded?: number }[];
  sources: {
    brand_id: string | null; scope?: HealthScope; source_label?: string | null; source: string; status: Status;
    coverage_through: string | null; last_ingested_at: string | null; message: string | null;
  }[];
  runs: { run_id: string; started_at: string; status: string; files_failed: number }[];
  failed_files: { run_id: string; file_name: string; error: string; scope?: HealthScope; brand_id?: string | null; source_label?: string | null; brand_name?: string | null; plain_reason?: string | null }[];
  unresolved_identities: { brand_id: string; source: string; raw_identifier: string; occurrences: number }[];
}

export interface AttentionItem {
  item_id: string;
  kind: "quiet_retainer" | "sample_no_video" | "missing_source";
  brand_id: string;
  title: string;
  rule: string;
  period_start: string;
  period_end: string;
  evidence_url: string;
  rank: number;
  impact_score: string | null; // USD exposure, null last
  impact_basis: string;
  why_needs_attention?: string;
  what_to_do?: string;
  incomplete_reason?: string | null;
  data_note?: string | null;
  brand_name?: string;
  creator_name?: string | null;
}
export interface Attention {
  data_revision: number;
  items: AttentionItem[];
}

export interface Explainer {
  what_it_means: string;
  why_it_matters: string;
  how_calculated: string;
  what_rows_prove: string;
}

export interface Evidence {
  label: string;
  definition: string;
  definition_version: string;
  period_start: string;
  period_end: string;
  timezone: string;
  result: MV;
  calculation: {
    kind: "sum" | "distinct_count" | "ratio" | "forecast" | "goal" | "decomposition";
    formula: string;
    inputs: { label: string; value: string | number | null; unit: string }[];
  };
  exclusions: { reason: string; count: number; amount: string | null }[];
  warnings: string[];
  columns: string[];
  records: { source_file: string; source_locator: string; included: boolean; values: Record<string, unknown> }[];
  records_truncated: boolean;
  explainer?: Explainer | null;
  what_this_means?: string;
  why_it_matters?: string;
  what_to_watch?: string;
  incomplete_reason?: string | null;
  data_note?: string | null;
  /** Plain column labels; records are rendered only through these. */
  columns_plain?: { key: string; label: string }[];
  total_count: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

/* ---------- Charts (amendment 2) ---------- */
export type SeriesName =
  | "pacing_trajectory" | "daily_gmv_refunds" | "attribution_reconciliation"
  | "sample_funnel_lag" | "creator_concentration" | "retainer_cadence";
export type ChartMetric = "gmv" | "videos" | "active_creators";

interface BasePoint {
  status: PointStatus;
  status_reason: string | null;
  /** field name -> relative evidence URL */
  evidence_urls: Record<string, string>;
}
export interface PacingPoint extends BasePoint {
  x: string; // YYYY-MM-DD
  actual: string | number | null; // cumulative
  projection: string | number | null;
  required: string | number | null;
}
export interface DailyGmvPoint extends BasePoint {
  x: string;
  gmv: string | null;
  creator_attributed_gmv: string | null;
  attributed_refunds_cohort: string | null;
  attributed_refunds_processed: string | null;
  net_attributed_sales: string | null;
}
export interface ReconciliationPoint extends BasePoint {
  x: "resolved" | "creator_unresolved" | "none" | "conflict";
  amount: string | null;
  order_items: number | null;
  pct: string | null; // fraction; sums to 1
}
export interface FunnelLagPoint extends BasePoint {
  group: "stage" | "lag";
  x: string; // sent|delivered|mature|in_transit|pending|converted|no_video_mature|unknown | 0-7|8-14|15-21|22-30
  count: number | null;
  pct_of_sent?: string | null; // stage points
  pct_of_converted?: string | null; // lag points
}
export interface ConcentrationPoint extends BasePoint {
  x: number; // rank
  brand_id?: string; // portfolio form
  creator_id: string;
  handle: string;
  gmv: string | null;
  share: string | null;
  cum_creator_pct: string | null;
  cum_gmv_pct: string | null;
}
export interface RetainerCadencePoint extends BasePoint {
  x: string; // YYYY-MM
  brand_id?: string; // portfolio form
  creator_id: string;
  handle: string;
  expected_posts: string | null;
  posts: number | null;
  attainment_pct: string | null;
}
export interface ChartSeriesMap {
  pacing_trajectory: PacingPoint;
  daily_gmv_refunds: DailyGmvPoint;
  attribution_reconciliation: ReconciliationPoint;
  sample_funnel_lag: FunnelLagPoint;
  creator_concentration: ConcentrationPoint;
  retainer_cadence: RetainerCadencePoint;
}
export interface PacingMeta {
  basis: MV | string | null;
  target: MV | null;
  projection: MV | null;
  required_pace: MV | null;
}
export type AvailabilityStatus = "available" | "stale" | "zero" | "unknown" | "empty" | "not_applicable";
export interface ChartAvailability { status: AvailabilityStatus; reason: string | null }
export interface ChartsAvailable {
  data_revision: number;
  series: { series_id: SeriesName; status: AvailabilityStatus; reason: string | null; as_of: string | null; point_count: number }[];
}

export interface ChartEnvelope<P> {
  availability?: ChartAvailability;
  series: SeriesName;
  brand_id: string | null;
  month: string;
  cutoff: string;
  data_revision: number;
  definition_version: string;
  coverage_through: string | null;
  status: PointStatus;
  status_reason: string | null;
  units: Record<string, string>;
  meta: Record<string, unknown> & Partial<PacingMeta> & { unresolved_gmv?: MV; top10_gmv_share?: string | null; top20_gmv_share?: string | null };
  points: P[];
}

/* ---------- Portfolio ---------- */
export interface PortfolioKpi {
  metric_key: string;
  value: MV;
  baseline: MV;
  delta: MV;
  delta_pct: MV;
  progress?: MV | null;
  brands_covered: number;
  brands_total: number;
}
export interface BrandPaceGoal { goal_name: string; status_label: string; actual_label: string | null; target_label: string | null; incomplete_reason: string | null }
export interface BrandPace { brand_slug: string; brand_name: string; status_label: string; data_note: string | null; goals: BrandPaceGoal[] }
export interface PortfolioKpis {
  data_revision: number;
  /** "Brands on pace: N of M" (on_track of total). */
  brand_pace_counts?: { on_track: number; behind: number; unknown: number; total: number };
  brand_pace?: BrandPace[];
  kpis: PortfolioKpi[];
  pace_counts: { on_track: number; at_risk: number; off_track: number; unknown: number };
}

/* ---------- Diagnostics ---------- */
/** One side of a comparison with its own plain reason when empty. */
export interface DiagSide { value: Val; unavailable_reason: string | null }
export interface DiagnosticsDelta { baseline: Val | DiagSide; current: Val | DiagSide; delta: Val | DiagSide }
export interface Diagnostics {
  periods: Record<string, unknown>;
  method: string;
  status: Status;
  disclaimer: string;
  total: DiagnosticsDelta;
  factors: { key: "A" | "V" | "G" | string; label?: string; baseline: Val | DiagSide; current: Val | DiagSide; effect: Val | DiagSide }[];
  notes?: string[];
  unlinked_older_gmv: DiagnosticsDelta;
  products: { product_id: string; name: string; gmv_baseline: Val; gmv_current: Val; delta: Val; observation: string }[];
}
