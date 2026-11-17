import { mockRequest } from "./mock-server";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "true";
export const DEMO_USER = process.env.NEXT_PUBLIC_DEMO_USERNAME || "demo";
export const DEMO_PASS = process.env.NEXT_PUBLIC_DEMO_PASSWORD || "darkroom-demo";
export const TOKEN_KEY = "darkroom_auth";

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
  }
}

export function getToken(): string | null {
  return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
}
export function setToken(t: string) {
  window.localStorage.setItem(TOKEN_KEY, t);
}
export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

/** Bodies of earlier 200 responses, used only if the server answers 304 and the browser did not substitute the cached body. */
const lastBody = new Map<string, unknown>();

function unauthorized(): never {
  clearToken();
  if (typeof window !== "undefined") window.location.href = "/login";
  throw new ApiError(401, "Unauthorized");
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  if (USE_MOCKS) {
    await new Promise((r) => setTimeout(r, 80));
    return JSON.parse(JSON.stringify(await mockRequest(method, path, body))) as T;
  }
  const token = getToken();
  // No custom conditional headers: CORS only allows Authorization + Content-Type. The browser revalidates
  // `Cache-Control: private, no-cache` responses with the ETag by itself and hands us the cached body.
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(API_BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 401) unauthorized();
  if (res.status === 304) {
    if (lastBody.has(path)) return lastBody.get(path) as T;
    throw new ApiError(304, "Not modified (no cached body)");
  }
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try { detail = (await res.json()).detail; } catch { /* ignore */ }
    throw new ApiError(res.status, detail);
  }
  const json = await res.json();
  if (method === "GET") lastBody.set(path, json);
  return json as T;
}

export const apiGet = <T,>(path: string) => request<T>("GET", path);
export const apiPost = <T,>(path: string, body: unknown) => request<T>("POST", path, body);

export async function login(username: string, password: string): Promise<void> {
  if (USE_MOCKS) {
    if (username !== DEMO_USER || password !== DEMO_PASS) throw new ApiError(401, "Invalid username or password");
    setToken("mock-token");
    return;
  }
  const res = await fetch(`${API_BASE}/api/v1/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username, password }),
  });
  if (!res.ok) throw new ApiError(res.status, res.status === 401 ? "Invalid username or password" : "Login failed");
  setToken((await res.json()).access_token);
}

/** Fetch one evidence page; on 409 refresh_required, refetch once with the current revision. */
export async function fetchEvidence<T>(evidenceUrl: string, offset = 0, limit = 100): Promise<T> {
  const build = (revision?: number) => {
    const u = new URL(evidenceUrl, "http://x");
    if (revision !== undefined) u.searchParams.set("revision", String(revision));
    u.searchParams.set("limit", String(limit));
    u.searchParams.set("offset", String(offset));
    return u.pathname + u.search;
  };
  try {
    return await apiGet<T>(build());
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      const d = e.detail as { code?: string; current_revision?: number } | null;
      if (d && d.code === "refresh_required" && d.current_revision !== undefined) return apiGet<T>(build(d.current_revision));
    }
    throw e;
  }
}
