/* Response fields, read defensively on top of the foundation types (all optional). */
import type { AttentionItem, PortfolioKpis } from "@/lib/types";

export interface BrandPaceGoal {
  goal_name: string; status_label: string; actual_label: string | null; target_label: string | null; incomplete_reason: string | null;
}
export interface BrandPace {
  brand_slug: string; brand_name: string; status_label: string; data_note: string | null; goals: BrandPaceGoal[];
}
export interface BrandPaceCounts { on_track: number; behind: number; unknown: number; total: number }
export type PortfolioKpisExt = PortfolioKpis & { brand_pace_counts?: BrandPaceCounts; brand_pace?: BrandPace[] };

export type AttentionItemExt = AttentionItem & {
  why_needs_attention?: string | null; what_to_do?: string | null; incomplete_reason?: string | null;
  data_note?: string | null; brand_name?: string | null; creator_name?: string | null;
};

export interface PlainFile {
  brand_name?: string | null; plain_reason?: string | null; scope?: "brand" | "shared"; brand_id?: string | null;
  source_label?: string | null; file_label?: string | null; plain_file_label?: string | null;
  excluded_rows?: number | null; rows_excluded?: number | null; count?: number | null;
}
