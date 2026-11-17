/* Local mock backend used when NEXT_PUBLIC_USE_MOCKS=true. Serves JSON from frontend/mocks (shapes = API contract). */
/* eslint-disable @typescript-eslint/no-explicit-any */
import meta from "@mocks/meta.json";
import overview from "@mocks/overview.json";
import attention from "@mocks/attention.json";
import dataHealth from "@mocks/data_health.json";
import evidence from "@mocks/evidence.json";
import portfolioKpis from "@mocks/portfolio_kpis.json";
import notes from "@mocks/notes.json";

const BRAND_IDS = ["aurelle", "verdant", "crunchwell", "threadline", "glowhaus"];
const DEMO_USER = process.env.NEXT_PUBLIC_DEMO_USERNAME || "demo";

class MockError extends Error {
  constructor(public status: number, public detail: unknown) { super(String(detail)); }
}

async function brandFile(prefix: string, id: string): Promise<any> {
  if (!BRAND_IDS.includes(id)) throw new MockError(404, "Unknown brand");
  return (await import(`../../mocks/${prefix}_${id}.json`)).default;
}

const noteStore: any[] = [...(notes as any).items];

async function mockGet(path: string): Promise<unknown> {
  const url = new URL(path, "http://mock");
  const p = url.pathname.replace(/^\/api\/v1/, "");
  const q = url.searchParams;
  if (p === "/meta") return meta;
  if (p === "/auth/me") return { username: DEMO_USER };
  if (p === "/overview") return overview;
  if (p === "/portfolio/kpis") return portfolioKpis;
  if (p === "/attention") {
    const a = attention as any;
    const bid = q.get("brand_id"), kind = q.get("kind");
    return { ...a, items: a.items.filter((i: any) => (!bid || i.brand_id === bid) && (!kind || i.kind === kind)) };
  }
  if (p === "/data-health") {
    const d = dataHealth as any;
    const bid = q.get("brand_id");
    if (!bid) return d;
    const ff = d.failed_files.filter((f: any) => f.scope === "shared" || f.brand_id === bid);
    return { ...d, sources: d.sources.filter((s: any) => s.scope === "shared" || s.brand_id === bid), failed_files: ff,
      counts: { brand_failed: ff.filter((f: any) => f.scope === "brand").length, shared_failed: 0, open_issues: d.counts.open_issues },
      unresolved_identities: d.unresolved_identities.filter((s: any) => s.brand_id === bid) };
  }
  if (p === "/portfolio/charts") {
    const all = (await import("../../mocks/charts_portfolio.json")).default as any;
    const s = all[q.get("series") || ""];
    if (!s) throw new MockError(422, "Unknown series");
    return s;
  }
  let m = p.match(/^\/brands\/([^/]+)\/charts\/available$/);
  if (m) return brandFile("charts_available", m[1]);
  m = p.match(/^\/brands\/([^/]+)\/charts$/);
  if (m) {
    const all = await brandFile("charts", m[1]);
    const s = all[q.get("series") || ""];
    if (!s) throw new MockError(422, "Unknown series");
    return s;
  }
  m = p.match(/^\/brands\/([^/]+)\/diagnostics$/);
  if (m) return brandFile("diagnostics", m[1]);
  m = p.match(/^\/brands\/([^/]+)\/creators\/([^/]+)\/notes$/);
  if (m) {
    const items = noteStore.filter((n) => n.brand_id === m![1] && n.creator_id === m![2]);
    return { items, total_count: items.length };
  }
  m = p.match(/^\/brands\/([^/]+)\/creators$/);
  if (m) {
    const c = await brandFile("creators", m[1]);
    let items = [...c.items];
    const s = (q.get("q") || "").toLowerCase();
    if (s) items = items.filter((i) => i.handle.toLowerCase().includes(s));
    if (q.get("contract_type")) items = items.filter((i) => i.contract_type === q.get("contract_type"));
    if (q.get("status")) items = items.filter((i) => i.coverage_status === q.get("status"));
    const sort = q.get("sort") || "handle";
    const dir = q.get("order") === "desc" ? -1 : 1;
    const keyOf = (i: any) => (sort === "handle" || sort === "last_post_date" ? i[sort] : i[sort]?.value == null ? null : Number(i[sort].value));
    items.sort((a, b) => {
      const x = keyOf(a), y = keyOf(b);
      if (x === null && y === null) return 0;
      if (x === null) return 1;
      if (y === null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * dir;
    });
    return { ...c, items };
  }
  m = p.match(/^\/brands\/([^/]+)\/samples$/);
  if (m) {
    const s = await brandFile("samples", m[1]);
    let items = s.items;
    if (q.get("status")) items = items.filter((i: any) => i.status === q.get("status"));
    if (q.get("creator_id")) items = items.filter((i: any) => i.creator_id === q.get("creator_id"));
    return { ...s, items };
  }
  m = p.match(/^\/metrics\/([^/]+)\/evidence$/);
  if (m) {
    const e = evidence as any;
    const limit = Math.min(Math.max(Number(q.get("limit") || 100), 1), 500);
    const offset = Number(q.get("offset") || 0);
    const slice = e.records.slice(offset, offset + limit);
    const next = offset + limit < e.records.length ? offset + limit : null;
    return { ...e, label: m[1].replace(/_/g, " "), result: { ...e.result, metric_key: m[1] }, records: slice, records_truncated: false, total_count: e.records.length, limit, offset, next_offset: next };
  }
  throw new MockError(404, "No mock for " + path);
}

export async function mockRequest(method: "GET" | "POST", path: string, body?: unknown): Promise<unknown> {
  try {
    if (method === "POST") {
      const m = path.match(/^\/api\/v1\/brands\/([^/]+)\/creators\/([^/]+)\/notes$/);
      const text = String((body as any)?.body ?? "").trim();
      if (!m) throw new MockError(404, "No mock for " + path);
      if (text.length < 1 || text.length > 2000) throw new MockError(422, "body must be 1 to 2000 characters");
      const note = { note_id: noteStore.length + 1, brand_id: m[1], creator_id: m[2], author: DEMO_USER, body: text, created_at: new Date().toISOString() };
      noteStore.unshift(note);
      return note;
    }
    return await mockGet(path);
  } catch (e) {
    if (e instanceof MockError) {
      const { ApiError } = await import("./api");
      throw new ApiError(e.status, e.detail);
    }
    throw e;
  }
}
