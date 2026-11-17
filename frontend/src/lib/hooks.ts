"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "./api";
import type {
  Attention, ChartEnvelope, ChartsAvailable, ChartMetric, ChartSeriesMap, CreatorNote, CreatorNotes, Creators, DataHealth,
  Diagnostics, Meta, Overview, PortfolioKpis, SeriesName, Samples,
} from "./types";

function qs(params: Record<string, string | number | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** /meta is polled lightly; its data_revision keys every other query, so a new revision refetches everything. */
export function useMeta() {
  return useQuery({ queryKey: ["meta"], queryFn: () => apiGet<Meta>("/api/v1/meta"), staleTime: 30_000, refetchInterval: 60_000 });
}
export function useRevision(): number | undefined {
  return useMeta().data?.data_revision;
}

/** Generic GET keyed by [path, data_revision]. Disabled until the revision is known or when path is null. */
export function useApiQuery<T>(path: string | null) {
  const revision = useRevision();
  return useQuery({
    queryKey: ["api", path, revision],
    queryFn: () => apiGet<T>(path as string),
    enabled: path !== null && revision !== undefined,
    staleTime: Infinity,
  });
}

export const useOverview = () => useApiQuery<Overview>("/api/v1/overview");
export const usePortfolioKpis = () => useApiQuery<PortfolioKpis>("/api/v1/portfolio/kpis");
export const useDataHealth = (brandId?: string) => useApiQuery<DataHealth>(`/api/v1/data-health${qs({ brand_id: brandId })}`);
export const useAttention = (p: { brandId?: string; kind?: string; followupDays?: number } = {}) =>
  useApiQuery<Attention>(`/api/v1/attention${qs({ brand_id: p.brandId, kind: p.kind, followup_days: p.followupDays })}`);

export interface CreatorFilters { q?: string; contract_type?: string; status?: string; sort?: string; order?: "asc" | "desc" }
export const useCreators = (brandId: string, f: CreatorFilters = {}) =>
  useApiQuery<Creators>(`/api/v1/brands/${brandId}/creators${qs({ ...f })}`);
export const useSamples = (brandId: string, f: { status?: string; creator_id?: string } = {}) =>
  useApiQuery<Samples>(`/api/v1/brands/${brandId}/samples${qs({ ...f })}`);
export const useDiagnostics = (brandId: string, p: { month?: string; cutoff?: string } = {}) =>
  useApiQuery<Diagnostics>(`/api/v1/brands/${brandId}/diagnostics${qs({ ...p })}`);

export interface ChartParams { month?: string; cutoff?: string; metric?: ChartMetric }
/** Brand chart series. brandId = null requests the portfolio form (all brands). */
export function useChartSeries<S extends SeriesName>(brandId: string | null, series: S, p: ChartParams = {}) {
  const base = brandId ? `/api/v1/brands/${brandId}/charts` : "/api/v1/portfolio/charts";
  return useApiQuery<ChartEnvelope<ChartSeriesMap[S]>>(`${base}${qs({ series, ...p })}`);
}

export const useCreatorNotes = (brandId: string, creatorId: string | null) =>
  useQuery({
    queryKey: ["notes", brandId, creatorId],
    queryFn: () => apiGet<CreatorNotes>(`/api/v1/brands/${brandId}/creators/${creatorId}/notes`),
    enabled: !!creatorId,
  });
/** Notes are append-only and never change data_revision, so only the notes query is invalidated. */
export function useAddCreatorNote(brandId: string, creatorId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: string) => apiPost<CreatorNote>(`/api/v1/brands/${brandId}/creators/${creatorId}/notes`, { body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notes", brandId, creatorId] }),
  });
}

/** Per-series availability classifier from the API (available|stale|zero|unknown|empty|not_applicable). The UI never decides this itself. */
export const useChartsAvailable = (brandId: string, p: { month?: string; cutoff?: string } = {}) =>
  useApiQuery<ChartsAvailable>(`/api/v1/brands/${brandId}/charts/available${qs({ ...p })}`);
