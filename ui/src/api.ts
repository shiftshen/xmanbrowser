// Thin client for the XMan local control API (FastAPI on 127.0.0.1:8723).
//
// Inside the Tauri webview, browser fetch to http://127.0.0.1 is blocked by
// WKWebView (ATS / mixed-content from the tauri:// origin). The Tauri HTTP
// plugin performs the request natively in Rust, bypassing that entirely. In a
// plain browser (dev) we use the normal fetch; CORS on the API is permissive.
import { fetch as tauriFetch } from "@tauri-apps/plugin-http";

const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
const xfetch: typeof fetch = isTauri ? (tauriFetch as typeof fetch) : window.fetch.bind(window);

export interface FingerprintSummary {
  os: string;
  userAgent: string;
  platform: string;
  hardwareConcurrency: number;
  screen: string;
  webglVendor: string;
  webglRenderer: string;
  canvasOffset: number;
  fontSpacingSeed: number;
}

export interface Profile {
  id: string;
  name: string;
  group: string;
  note: string;
  proxy_raw: string | null;
  os: string;
  fingerprint: FingerprintSummary;
  running: boolean;
  engine: string;
  user_data_dir?: string;
}

export interface GeoInfo {
  ip: string;
  country?: string;
  country_code?: string;
  city?: string;
  timezone?: string;
  latitude?: number;
  longitude?: number;
}

export interface PoolProxy {
  id: string;
  label: string;
  raw: string;
  note: string;
  last_ip: string | null;
  last_country: string | null;
  last_cc: string | null;
  last_tz: string | null;
  last_ok: boolean | null;
  checked_at: number | null;
  enabled: boolean;
  fail_count: number;
  success_count: number;
  source: string | null;
  group: string;
}

export interface Group {
  name: string;
  count: number;
}

export interface EngineStatus {
  engine: string;
  state: "ready" | "downloading" | "missing" | "error" | "unknown";
  percent: number;
  message: string;
}

export interface Provider {
  id: string;
  label: string;
  kind: "api_extract" | "rotating_gateway";
  url: string;
  note: string;
  last_count: number | null;
  refreshed_at: number | null;
}

// In the Tauri production webview the app loads from tauri://localhost, where a
// relative "/api" has no dev proxy to ride on — so always target the control
// service's absolute localhost URL. The API enables permissive CORS, so this
// works equally from the Vite dev server, a plain browser, and the Tauri webview.
// Override with VITE_XMAN_API if the service runs on a non-default host/port.
const API_ORIGIN = (import.meta as any).env?.VITE_XMAN_API ?? "http://127.0.0.1:8723";
const BASE = `${API_ORIGIN}/api`;

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const b = await r.json();
      msg = b.detail ?? msg;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return r.status === 204 ? (undefined as T) : r.json();
}

export const api = {
  health: () => xfetch(`${BASE}/health`).then((r) => j<{ ok: boolean; version: string }>(r)),

  list: (search?: string, group?: string) => {
    const q = new URLSearchParams();
    if (search) q.set("search", search);
    if (group) q.set("group", group);
    return xfetch(`${BASE}/profiles?${q}`).then((r) => j<Profile[]>(r));
  },

  get: (id: string) => xfetch(`${BASE}/profiles/${id}`).then((r) => j<Profile>(r)),

  create: (body: {
    name?: string;
    os: string;
    engine?: string;
    proxy?: string | null;
    group?: string;
    note?: string;
    seed?: number | null;
  }) =>
    xfetch(`${BASE}/profiles`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => j<Profile>(r)),

  update: (id: string, body: Partial<Pick<Profile, "name" | "group" | "note">> & { proxy?: string }) =>
    xfetch(`${BASE}/profiles/${id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => j<Profile>(r)),

  remove: (id: string) => xfetch(`${BASE}/profiles/${id}`, { method: "DELETE" }).then((r) => j<void>(r)),

  clone: (id: string, newName: string, regen = true) =>
    xfetch(`${BASE}/profiles/${id}/clone?new_name=${encodeURIComponent(newName)}&regenerate_fingerprint=${regen}`, {
      method: "POST",
    }).then((r) => j<Profile>(r)),

  launch: (id: string, url = "about:blank", headless = false) =>
    xfetch(`${BASE}/profiles/${id}/launch`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url, headless }),
    }).then((r) => j<{ pid?: number; already_running?: boolean; engine_downloading?: string; status?: EngineStatus }>(r)),

  engineStatus: () => xfetch(`${BASE}/engine/status`).then((r) => j<Record<string, EngineStatus>>(r)),

  stop: (id: string) => xfetch(`${BASE}/profiles/${id}/stop`, { method: "POST" }).then((r) => j<{ stopped: boolean }>(r)),

  batchLaunch: (ids: string[]) =>
    xfetch(`${BASE}/batch/launch`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ ids }),
    }).then((r) => j<any[]>(r)),
  batchStop: (ids: string[]) =>
    xfetch(`${BASE}/batch/stop`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ ids }),
    }).then((r) => j<any[]>(r)),

  checkProxy: (proxy: string) =>
    xfetch(`${BASE}/proxy/check?proxy=${encodeURIComponent(proxy)}`).then((r) => j<GeoInfo>(r)),
  parseProxy: (raw: string) =>
    xfetch(`${BASE}/proxy/parse?raw=${encodeURIComponent(raw)}`).then((r) =>
      j<{ ok: boolean; error?: string; scheme?: string; host?: string; port?: number; has_auth?: boolean }>(r)),

  exportAll: () => xfetch(`${BASE}/export`).then((r) => j<any[]>(r)),

  importProfiles: (profiles: any[]) =>
    xfetch(`${BASE}/import`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(profiles),
    }).then((r) => j<any[]>(r)),

  // auto-name
  nextName: () => xfetch(`${BASE}/next-name`).then((r) => j<{ name: string }>(r)),

  // groups
  groups: () => xfetch(`${BASE}/groups`).then((r) => j<Group[]>(r)),
  addGroup: (name: string) =>
    xfetch(`${BASE}/groups`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }),
    }).then((r) => j<Group[]>(r)),
  deleteGroup: (name: string) =>
    xfetch(`${BASE}/groups/${encodeURIComponent(name)}`, { method: "DELETE" }).then((r) => j<void>(r)),

  // proxy pool
  proxies: () => xfetch(`${BASE}/proxies`).then((r) => j<PoolProxy[]>(r)),
  addProxy: (raw: string, label?: string, note = "", group = "") =>
    xfetch(`${BASE}/proxies`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ raw, label, note, group }),
    }).then((r) => j<PoolProxy>(r)),
  addProxiesBulk: (text: string) =>
    xfetch(`${BASE}/proxies/bulk`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text }),
    }).then((r) => j<{ added: PoolProxy[]; errors: { line: string; error: string }[] }>(r)),
  updateProxy: (id: string, body: Partial<Pick<PoolProxy, "label" | "raw" | "note" | "group">>) =>
    xfetch(`${BASE}/proxies/${id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => j<PoolProxy>(r)),
  deleteProxy: (id: string) =>
    xfetch(`${BASE}/proxies/${id}`, { method: "DELETE" }).then((r) => j<void>(r)),
  checkPoolProxy: (id: string) =>
    xfetch(`${BASE}/proxies/${id}/check`, { method: "POST" }).then((r) => j<PoolProxy>(r)),
  setProxyEnabled: (id: string, enabled: boolean) =>
    xfetch(`${BASE}/proxies/${id}/enabled?enabled=${enabled}`, { method: "POST" }).then((r) => j<PoolProxy>(r)),
  checkAllProxies: () =>
    xfetch(`${BASE}/proxies/check-all`, { method: "POST" }).then((r) => j<{ checked: number; ok: number; failed: number }>(r)),

  // dynamic proxy providers
  providers: () => xfetch(`${BASE}/providers`).then((r) => j<Provider[]>(r)),
  addProvider: (kind: string, url: string, label?: string, note = "") =>
    xfetch(`${BASE}/providers`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ kind, url, label, note }),
    }).then((r) => j<Provider>(r)),
  deleteProvider: (id: string) =>
    xfetch(`${BASE}/providers/${id}`, { method: "DELETE" }).then((r) => j<void>(r)),
  refreshProvider: (id: string) =>
    xfetch(`${BASE}/providers/${id}/refresh`, { method: "POST" }).then((r) => j<{ fetched: number; added: number }>(r)),
};
