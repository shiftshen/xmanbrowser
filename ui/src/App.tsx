import { useCallback, useEffect, useRef, useState } from "react";
import { openUrl } from "@tauri-apps/plugin-opener";
import { save as dlgSave, open as dlgOpen } from "@tauri-apps/plugin-dialog";
import { check as checkUpdate } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";
import { invoke } from "@tauri-apps/api/core";
import { api, DetectResult, EngineStatus, GeoInfo, Group, PoolProxy, Profile, Provider } from "./api";
import { useT, getLang, setLang } from "./i18n";

// A webview <a target="_blank"> opens nothing; route external links through the
// OS browser via the Tauri opener (plain window.open as the dev-browser fallback).
const _inTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
function openExternal(e: React.MouseEvent, url: string) {
  e.preventDefault();
  if (_inTauri) openUrl(url).catch(() => window.open(url, "_blank"));
  else window.open(url, "_blank", "noreferrer");
}
import logoShield from "./assets/logo-shield.png";
import logo711 from "./assets/offers/711proxy.svg";
import logoWebshare from "./assets/offers/webshare.svg";

type Toast = { msg: string; err?: boolean } | null;
type View = "profiles" | "proxies";

// Proxy affiliate placements (referral links). Two picks: one premium /
// Chinese-payment-friendly, one budget with a free tier.
const PROXY_OFFERS: { tierKey: string; logo: string; alt: string; subKey: string; href: string }[] = [
  { tierKey: "offer.tier.711", logo: logo711, alt: "711Proxy", subKey: "offer.sub.711", href: "https://www.711proxy.com/signup?code=812411" },
  { tierKey: "offer.tier.webshare", logo: logoWebshare, alt: "Webshare", subKey: "offer.sub.webshare", href: "https://www.webshare.io/?referral_code=a408k2bpaeid" },
];

// Affiliate CTA shown when a detection comes back dirty (→ buy clean proxies).
const CLEAN_IP_CTA = PROXY_OFFERS[0]; // 711Proxy

// Default page a profile opens to (instead of a blank tab). A neutral, light
// page — NOT a fingerprint checker: whoer.net's aggressive WebGL/canvas probing
// crashes Camoufox's GPU process on some Windows machines. To inspect a
// profile's IP/fingerprint, use the per-card 🛡 check (it doesn't launch a tab).
const HOME_URL = "https://www.google.com/";

const AVATAR_COLORS = ["#4f8cff", "#7b5cff", "#3fb950", "#d6a338", "#f0533f", "#27b3b3", "#e06cc8"];
function avatarColor(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}
const initials = (s: string) => s.replace(/[^a-zA-Z0-9]/g, "").slice(0, 2).toUpperCase() || "·";

function BrandMark() {
  return <img className="mark" src={logoShield} width={34} height={34} alt="XmanBrowser" />;
}

export function App() {
  const t = useT();
  const [view, setView] = useState<View>("profiles");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [proxies, setProxies] = useState<PoolProxy[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [editingProvider, setEditingProvider] = useState<boolean>(false);
  const [group, setGroup] = useState<string>(""); // "" = all
  const [search, setSearch] = useState("");
  const [online, setOnline] = useState<boolean | null>(null);
  const [version, setVersion] = useState("");
  const [connErr, setConnErr] = useState("");
  const [editing, setEditing] = useState<Profile | "new" | null>(null);
  const [editingProxy, setEditingProxy] = useState<PoolProxy | "new" | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [detail, setDetail] = useState<Profile | null>(null);
  const [engineDl, setEngineDl] = useState<{ engine: string; profileId: string; url?: string } | null>(null);
  const [toast, setToast] = useState<Toast>(null);
  // In-app confirm/prompt — Tauri's WKWebview ignores window.confirm/prompt, so
  // native dialogs silently no-op (that's why Delete did nothing). Use modals.
  const [confirmDlg, setConfirmDlg] = useState<{ msg: string; onYes: () => void } | null>(null);
  const [promptDlg, setPromptDlg] = useState<{ msg: string; placeholder: string; onYes: (v: string) => void } | null>(null);
  const askConfirm = (msg: string, onYes: () => void) => setConfirmDlg({ msg, onYes });
  const askPrompt = (msg: string, onYes: (v: string) => void, placeholder = "") => setPromptDlg({ msg, placeholder, onYes });
  // In-app auto-update: check the GitHub release manifest on startup; if newer,
  // a banner downloads + installs + relaunches.
  const [update, setUpdate] = useState<any>(null);
  const [updPct, setUpdPct] = useState<number | null>(null);
  useEffect(() => {
    if (!_inTauri) return;
    checkUpdate().then((u) => { if (u) setUpdate(u); }).catch(() => { /* offline / no update */ });
  }, []);
  const doUpdate = async () => {
    if (!update) return;
    setUpdPct(0);
    try {
      let total = 0, got = 0;
      await update.downloadAndInstall((e: any) => {
        if (e.event === "Started") total = e.data?.contentLength ?? 0;
        else if (e.event === "Progress") { got += e.data?.chunkLength ?? 0; setUpdPct(total ? Math.round((got / total) * 100) : 0); }
      });
      await relaunch();
    } catch (e: any) { flash(e.message || "update failed", true); setUpdPct(null); }
  };
  const fileRef = useRef<HTMLInputElement>(null);

  const flash = useCallback((msg: string, err = false) => {
    setToast({ msg, err });
    setTimeout(() => setToast(null), 2600);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [ps, gs, px, pv] = await Promise.all([api.list(search), api.groups(), api.proxies(), api.providers()]);
      setProfiles(ps);
      setGroups(gs);
      setProxies(px);
      setProviders(pv);
    } catch (e: any) {
      flash(e.message, true);
    }
  }, [search, flash]);

  // poll backend until reachable; keep badges live. Poll fast at first so the
  // few-second startup feels snappy; only surface a technical error if it stays
  // down well past a normal cold start.
  const startRef = useRef<number>(Date.now());
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const h = await api.health();
        if (cancelled) return;
        setVersion(h.version);
        setConnErr("");
        setOnline((was) => {
          if (!was) refresh();
          return true;
        });
        await refresh();
      } catch (e: any) {
        if (!cancelled) {
          setOnline(false);
          // hide the raw error during the normal startup window (~15s)
          const waited = Date.now() - startRef.current;
          setConnErr(waited > 15000 ? String(e?.message ?? e) : "");
        }
      }
      if (!cancelled) {
        const waited = Date.now() - startRef.current;
        timer = setTimeout(tick, online ? 2500 : waited < 12000 ? 700 : 2500);
      }
    };
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []); // eslint-disable-line

  const act = async (fn: () => Promise<any>, ok?: string) => {
    try {
      await fn();
      if (ok) flash(ok);
      await refresh();
    } catch (e: any) {
      flash(e.message, true);
    }
  };

  // Launch a profile; if its engine isn't downloaded yet, open the progress
  // modal (which downloads, then auto-launches) instead of silently failing.
  const launchProfile = async (p: Profile, url?: string) => {
    try {
      const res = await api.launch(p.id, url ?? HOME_URL);
      if (res.engine_downloading) {
        setEngineDl({ engine: res.engine_downloading, profileId: p.id, url });
      } else {
        flash(`launched ${p.name}`);
        refresh();
      }
    } catch (e: any) {
      flash(e.message, true);
    }
  };

  const importText = async (text: string) => {
    const data = JSON.parse(text);
    const res = await api.importProfiles(Array.isArray(data) ? data : [data]);
    flash(`${t("tb.import")} ✓ ${res.filter((r) => !r.error).length}`);
    refresh();
  };
  // Export via a native Save dialog + a Rust write (the webview's blob download
  // is unreliable and would silently produce a broken file). Only report success
  // after the file is actually written. Falls back to a blob in the dev browser.
  const onExport = async () => {
    const data = await api.exportAll();
    const contents = JSON.stringify(data, null, 2);
    if (_inTauri) {
      try {
        const path = await dlgSave({ defaultPath: "xman-profiles.json", filters: [{ name: "JSON", extensions: ["json"] }] });
        if (!path) return; // user cancelled
        await invoke("save_text", { path, contents });
        flash(`${t("tb.export")} ✓ ${data.length}`);
      } catch (e: any) { flash(e.message || "export failed", true); }
    } else {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([contents], { type: "application/json" }));
      a.download = "xman-profiles.json"; a.click();
      flash(`${t("tb.export")} ✓ ${data.length}`);
    }
  };
  const onImport = async () => {
    if (_inTauri) {
      try {
        const path = await dlgOpen({ multiple: false, filters: [{ name: "JSON", extensions: ["json"] }] });
        if (!path || typeof path !== "string") return;
        await importText(await invoke<string>("read_text", { path }));
      } catch (e: any) { flash(e.message || "import failed", true); }
    } else {
      fileRef.current?.click(); // dev browser → hidden file input
    }
  };
  const onImportFile = async (f: File) => {
    try { await importText(await f.text()); }
    catch (e: any) { flash(e.message, true); }
  };

  const visible = profiles.filter((p) => !group || p.group === group);
  const addGroup = () => {
    askPrompt(t("dlg.newGroupName"), (n) => {
      if (n.trim()) act(() => api.addGroup(n.trim()), "group added");
    }, t("dlg.newGroupPlaceholder"));
  };

  return (
    <div className="app">
      {/* ---------------- sidebar ---------------- */}
      <aside className="sidebar">
        <div className="brand">
          <BrandMark />
          <div className="wordmark">
            <div className="name">Xman<span>Browser</span></div>
            <div className="tag">by <b>XmanX</b></div>
          </div>
        </div>

        <div className="nav-label">{t("nav.profiles")}</div>
        <div
          className={`nav-item ${view === "profiles" && !group ? "active" : ""}`}
          onClick={() => { setView("profiles"); setGroup(""); }}
        >
          <span className="ico">▦</span> {t("nav.allProfiles")}
          <span className="grow" />
          <span className="count">{profiles.length}</span>
        </div>
        {groups.map((g) => (
          <div
            key={g.name}
            className={`nav-item ${view === "profiles" && group === g.name ? "active" : ""}`}
            onClick={() => { setView("profiles"); setGroup(g.name); }}
          >
            <span className="ico">●</span> {g.name}
            <span className="grow" />
            <span className="count">{g.count}</span>
          </div>
        ))}
        <div className="nav-item nav-add" onClick={addGroup}><span className="ico">＋</span> {t("nav.newGroup")}</div>

        <div className="nav-label">{t("nav.network")}</div>
        <div className={`nav-item ${view === "proxies" ? "active" : ""}`} onClick={() => setView("proxies")}>
          <span className="ico">⇄</span> {t("nav.proxyPool")}
          <span className="grow" />
          <span className="count">{proxies.length}</span>
        </div>

        {/* always-visible proxy affiliate — clean residential/ISP IPs */}
        <div className="nav-aff">
          <div className="nav-aff-title">{t("nav.getProxies")}</div>
          {PROXY_OFFERS.map((o) => (
            <a className="nav-aff-item" key={o.href} href={o.href} onClick={(e) => openExternal(e, o.href)} title={t(o.subKey)}>
              <img src={o.logo} alt={o.alt} />
              <span className="nav-aff-tag">{t(o.tierKey)}</span>
            </a>
          ))}
        </div>

        <div className="spacer" />
        <button className="lang-toggle" onClick={() => setLang(getLang() === "en" ? "zh" : "en")} title="Language / 语言">
          🌐 {t("lang.toggle")}
        </button>
        <div className="api-pill">
          <span className={`dot ${online === null ? "wait" : online ? "ok" : "bad"}`} />
          {online === null ? t("status.connecting") : online ? `${t("status.connected")} · v${version}` : t("status.starting")}
        </div>
      </aside>

      {/* ---------------- main ---------------- */}
      <div className="main">
        {update && (
          <div className="update-banner">
            <span>🎉 {t("upd.available", update.version)}</span>
            <span className="grow" />
            {updPct == null ? (
              <>
                <button className="primary sm" onClick={doUpdate}>{t("upd.now")}</button>
                <button className="sm" onClick={() => setUpdate(null)}>{t("upd.later")}</button>
              </>
            ) : (
              <span className="upd-progress">{t("upd.updating", updPct)}</span>
            )}
          </div>
        )}
        <div className="toolbar">
          {view === "profiles" ? (
            <h1>{group || t("nav.allProfiles")} <span className="sub">{visible.length}</span></h1>
          ) : (
            <h1>{t("nav.proxyPool")} <span className="sub">{proxies.length}</span></h1>
          )}
          <div className="grow" />
          {view === "profiles" ? (
            <>
              <input className="search" placeholder={t("tb.search")} value={search}
                onChange={(e) => { setSearch(e.target.value); }} />
              {(() => {
                const idle = visible.filter((p) => !p.running).map((p) => p.id);
                const live = visible.filter((p) => p.running).map((p) => p.id);
                return (
                  <>
                    {idle.length > 0 && (
                      <button onClick={() => act(() => api.batchLaunch(idle, HOME_URL), `launching ${idle.length}`)}>{t("tb.launchAll")}</button>
                    )}
                    {live.length > 0 && (
                      <button className="danger" onClick={() => act(() => api.batchStop(live), `stopping ${live.length}`)}>{t("tb.stopAll")}</button>
                    )}
                  </>
                );
              })()}
              <button onClick={onImport}>{t("tb.import")}</button>
              <button onClick={onExport}>{t("tb.export")}</button>
              <button className="primary" onClick={() => setEditing("new")}>{t("tb.newProfile")}</button>
              <input ref={fileRef} type="file" accept="application/json" style={{ display: "none" }}
                onChange={(e) => e.target.files?.[0] && onImportFile(e.target.files[0])} />
            </>
          ) : (
            <>
              <button onClick={() => act(() => api.checkAllProxies(), "tested all")} disabled={proxies.length === 0}>{t("tb.testAll")}</button>
              <button onClick={() => setBulkOpen(true)}>{t("tb.bulkImport")}</button>
              <button className="primary" onClick={() => setEditingProxy("new")}>{t("tb.addProxy")}</button>
            </>
          )}
        </div>

        <div className="content">
          {!online ? (
            <div className="loading">
              <div className="spinner" />
              <div className="big">Starting the local engine…</div>
              <div className="muted">This launches automatically — the first start can take a few seconds.</div>
              {connErr && (
                <div className="retry-note">
                  Still starting. On a fresh machine the browser engine may be downloading.
                  <div style={{ color: "#ff8a7d", fontSize: 11, marginTop: 6 }}>{connErr}</div>
                </div>
              )}
            </div>
          ) : (
            <>
              {view === "proxies" ? (
                <ProxiesView
                  proxies={proxies}
                  providers={providers}
                  onAdd={() => setEditingProxy("new")}
                  onEdit={(p) => setEditingProxy(p)}
                  onCheck={(p) => act(() => api.checkPoolProxy(p.id), "checked")}
                  onToggle={(p) => act(() => api.setProxyEnabled(p.id, !p.enabled))}
                  onDelete={(p) => askConfirm(t("dlg.deleteProxy", p.label), () => act(() => api.deleteProxy(p.id), "deleted"))}
                  onAddProvider={() => setEditingProvider(true)}
                  onRefreshProvider={(pv) => act(() => api.refreshProvider(pv.id), "refreshed from provider")}
                  onDeleteProvider={(pv) => askConfirm(t("dlg.deleteProvider", pv.label), () => act(() => api.deleteProvider(pv.id), "deleted"))}
                />
              ) : visible.length === 0 ? (
                <div className="empty">
                  <div className="big">{t("empty.title", group ? t("empty.titleIn", group) : t("empty.titleYet"))}</div>
                  {t("empty.hint")}
                </div>
              ) : (
                <div className="grid">
                  {visible.map((p) => (
                    <ProfileCard
                      key={p.id} p={p}
                      proxies={proxies}
                      onLaunch={() => launchProfile(p)}
                      onStop={() => act(() => api.stop(p.id), `stopped ${p.name}`)}
                      onEdit={() => setEditing(p)}
                      onDetail={async () => setDetail(await api.get(p.id))}
                      onClone={() => act(() => api.clone(p.id, `${p.name}-copy`), "cloned")}
                      onDelete={() => askConfirm(t("dlg.deleteProfile", p.name), () => act(() => api.remove(p.id), "deleted"))}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {editing && (
        <ProfileModal
          profile={editing === "new" ? null : editing}
          groups={groups} proxies={proxies}
          defaultGroup={group}
          onClose={() => setEditing(null)}
          onSaved={(m) => { setEditing(null); flash(m); refresh(); }}
          onError={(m) => flash(m, true)}
        />
      )}
      {editingProxy && (
        <ProxyModal
          proxy={editingProxy === "new" ? null : editingProxy}
          onClose={() => setEditingProxy(null)}
          onSaved={(m) => { setEditingProxy(null); flash(m); refresh(); }}
          onError={(m) => flash(m, true)}
        />
      )}
      {editingProvider && (
        <ProviderModal
          onClose={() => setEditingProvider(false)}
          onSaved={(m) => { setEditingProvider(false); flash(m); refresh(); }}
          onError={(m) => flash(m, true)}
        />
      )}
      {bulkOpen && (
        <BulkProxyModal
          onClose={() => setBulkOpen(false)}
          onDone={(n, skipped) => { setBulkOpen(false); flash(`added ${n} prox${n === 1 ? "y" : "ies"}${skipped ? `, ${skipped} skipped` : ""}`); refresh(); }}
          onError={(m) => flash(m, true)}
        />
      )}
      {detail && <DetailModal p={detail} onClose={() => setDetail(null)} />}
      {engineDl && (
        <EngineDownloadModal
          engine={engineDl.engine}
          onClose={() => setEngineDl(null)}
          onReady={async () => {
            const id = engineDl.profileId;
            const url = engineDl.url ?? HOME_URL;
            setEngineDl(null);
            try { await api.launch(id, url); flash("launched"); refresh(); }
            catch (e: any) { flash(e.message, true); }
          }}
        />
      )}
      {toast && <div className={`toast ${toast.err ? "err" : ""}`}>{toast.msg}</div>}

      {confirmDlg && (
        <div className="overlay" onClick={() => setConfirmDlg(null)}>
          <div className="modal sm-modal" onClick={(e) => e.stopPropagation()}>
            <h2>{t("dlg.confirm")}</h2>
            <div className="desc">{confirmDlg.msg}</div>
            <div className="foot">
              <button onClick={() => setConfirmDlg(null)}>{t("dlg.cancel")}</button>
              <button className="danger" onClick={() => { confirmDlg.onYes(); setConfirmDlg(null); }}>{t("dlg.delete")}</button>
            </div>
          </div>
        </div>
      )}

      {promptDlg && <PromptModal {...promptDlg} onClose={() => setPromptDlg(null)} />}
    </div>
  );
}

function PromptModal(props: { msg: string; placeholder: string; onYes: (v: string) => void; onClose: () => void }) {
  const [v, setV] = useState("");
  const t = useT();
  const submit = () => { props.onYes(v); props.onClose(); };
  return (
    <div className="overlay" onClick={props.onClose}>
      <div className="modal sm-modal" onClick={(e) => e.stopPropagation()}>
        <h2>{props.msg}</h2>
        <div className="field">
          <input autoFocus value={v} placeholder={props.placeholder}
            onChange={(e) => setV(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") submit(); if (e.key === "Escape") props.onClose(); }} />
        </div>
        <div className="foot">
          <button onClick={props.onClose}>{t("dlg.cancel")}</button>
          <button className="primary" onClick={submit}>{t("dlg.ok")}</button>
        </div>
      </div>
    </div>
  );
}

// ---------------- detection result ----------------
// Rows are built here from the result's structured fields (not the backend's
// pre-formatted text) so they follow the UI language.
function detectRows(r: DetectResult, t: (k: string, ...a: (string | number)[]) => string) {
  const rows: { k: string; v: string; ok: boolean | null }[] = [];
  const loc = [r.city, r.country].filter(Boolean).join(", ") || "unknown";
  rows.push({ k: t("det.row.ipRegion"), v: `${r.ip} · ${loc}`, ok: true });
  if (r.isp) rows.push({ k: t("det.row.isp"), v: r.isp, ok: true });
  const typeKey = r.ip_type === "residential" ? "det.type.residential"
    : r.ip_type === "mobile" ? "det.type.mobile"
    : r.ip_type === "datacenter" ? "det.type.datacenter" : "det.type.unknown";
  rows.push({ k: t("det.row.ipType"), v: t(typeKey), ok: r.ip_type === "residential" || r.ip_type === "mobile" ? true : r.ip_type === "datacenter" ? false : null });
  if (r.flags?.hosting && r.ip_type !== "datacenter") rows.push({ k: t("det.row.hosting"), v: t("det.hosting.hit"), ok: false });
  rows.push({ k: t("det.row.proxyCheck"), v: r.flags?.proxy ? t("det.proxy.flagged") : t("det.proxy.clean"), ok: !r.flags?.proxy });
  return rows;
}

function DetectResultPanel(props: { result: DetectResult | null; err: string | null; onClose: () => void; inCard?: boolean; subtitle?: string }) {
  const { result, err } = props;
  const t = useT();
  return (
    <div className={`detect-result-panel ${props.inCard ? "in-card" : ""}`}>
      <div className="drp-head">
        <span className="sec-title">{t("det.title")} <span className="faint">· {props.subtitle || t("det.subCurrent")}</span></span>
        <button className="sm ghost iconbtn" title={t("dlg.cancel")} onClick={props.onClose}>✕</button>
      </div>
      {err ? (
        <div className="detect-err">{t("det.fail", err)}</div>
      ) : result && (
        <div className="detect-result">
          <div className={`score-badge ${result.rating}`}>
            <span className="score-num">{result.score}</span>
            <span className="score-label">{t(`det.rating.${result.rating}`)}</span>
          </div>
          <div className="detect-rows">
            {detectRows(result, t).map((r, i) => (
              <div className="detect-row" key={i}>
                <span className={`drow-dot ${r.ok === false ? "bad" : r.ok === true ? "good" : "unk"}`} />
                <span className="drow-k">{r.k}</span>
                <span className="drow-v">{r.v}</span>
              </div>
            ))}
            {result.rating !== "clean" && (
              <a className="detect-cta" href={CLEAN_IP_CTA.href} onClick={(e) => openExternal(e, CLEAN_IP_CTA.href)}>
                {t("det.cta")}
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------- profile card ----------------
function ProfileCard(props: {
  p: Profile; proxies: PoolProxy[];
  onLaunch: () => void; onStop: () => void; onEdit: () => void;
  onDetail: () => void; onClone: () => void; onDelete: () => void;
}) {
  const { p } = props;
  const t = useT();
  const f = p.fingerprint;
  const pool = props.proxies.find((x) => x.raw === p.proxy_raw);
  const proxyOk = pool?.last_ok;
  const [det, setDet] = useState<DetectResult | null>(null);
  const [detErr, setDetErr] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);
  const runDetect = async () => {
    setDetecting(true); setDetErr(null); setDet(null);
    try { setDet(await api.detect(p.proxy_raw || "")); }
    catch (e: any) { setDetErr(e.message || "failed"); }
    finally { setDetecting(false); }
  };
  return (
    <div className="card">
      <div className="head">
        <div className="avatar" style={{ background: avatarColor(p.name) }}>{initials(p.name)}</div>
        <span className="title">{p.name}</span>
        <span className="chip" title={p.engine === "chromium" ? "Chromium (patchright)" : "Camoufox (Firefox)"}>{p.engine === "chromium" ? "Chrome" : "Firefox"}</span>
        <span className="grow" />
        {p.running && <span className="chip run">{t("card.running")}</span>}
        <button className="card-detect-btn" disabled={detecting} onClick={runDetect}>
          {detecting ? t("card.checking") : t("card.check")}
        </button>
      </div>
      <div className="specs" onClick={props.onDetail} style={{ cursor: "pointer" }}>
        <div className="line"><span className="k">{t("card.system")}</span><b style={{ textTransform: "capitalize" }}>{p.os}</b> · {f.screen} · {f.hardwareConcurrency} {t("card.cores")}</div>
        <div className="line"><span className="k">{t("card.webgl")}</span><b>{f.webglRenderer}</b></div>
        <div className="line"><span className="k">{t("card.proxy")}</span>
          {p.proxy_raw ? (
            <span className="proxy-tag">
              <span className="pdot" style={{ background: proxyOk === true ? "#3fb950" : proxyOk === false ? "#f0533f" : "#5c6678" }} />
              <b>{pool ? pool.label : p.proxy_raw}</b>
              {pool?.last_cc && <span className="faint">· {pool.last_cc}</span>}
            </span>
          ) : <b className="faint">{t("card.noProxy")}</b>}
        </div>
        {p.note && <div className="note">“{p.note}”</div>}
      </div>
      <div className="row" style={{ display: "flex", gap: 6 }}>
        {p.group !== "default" && <span className="chip grp">{p.group}</span>}
      </div>
      <div className="actions">
        {p.running
          ? <button className="danger" onClick={props.onStop}>{t("card.stop")}</button>
          : <button className="primary" onClick={props.onLaunch}>{t("card.launch")}</button>}
        <button className="sm" onClick={props.onEdit}>{t("card.edit")}</button>
        <button className="sm" onClick={props.onClone}>{t("card.clone")}</button>
        <button className="sm ghost danger iconbtn" onClick={props.onDelete}>✕</button>
      </div>
      {(det || detErr) && (
        <DetectResultPanel result={det} err={detErr} inCard
          subtitle={p.proxy_raw ? t("det.subProxy") : t("det.subDirect")}
          onClose={() => { setDet(null); setDetErr(null); }} />
      )}
    </div>
  );
}

// ---------------- proxies view ----------------
function ProxiesView(props: {
  proxies: PoolProxy[]; providers: Provider[];
  onAdd: () => void; onEdit: (p: PoolProxy) => void;
  onCheck: (p: PoolProxy) => void; onToggle: (p: PoolProxy) => void; onDelete: (p: PoolProxy) => void;
  onAddProvider: () => void; onRefreshProvider: (p: Provider) => void; onDeleteProvider: (p: Provider) => void;
}) {
  const [offersOpen, setOffersOpen] = useState(false);
  const t = useT();
  const mask = (raw: string) => raw.replace(/:([^:@/]+)@/, ":••••@");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
      {/* providers panel */}
      <div className="providers">
        <div className="providers-head">
          <span className="sec-title">{t("prov.title")} <span className="faint">· {t("prov.subtitle")}</span></span>
          <button className="sm primary" onClick={props.onAddProvider}>{t("prov.add")}</button>
        </div>
        {props.providers.length === 0 ? (
          <div className="faint" style={{ fontSize: 12.5, padding: "4px 2px" }}>
            {t("prov.empty")}
          </div>
        ) : (
          <div className="prov-list">
            {props.providers.map((pv) => (
              <div className="prov" key={pv.id}>
                <span className="chip">{pv.kind === "api_extract" ? "API" : "gateway"}</span>
                <b>{pv.label}</b>
                <span className="raw" style={{ flex: 1 }}>{pv.url}</span>
                {pv.last_count != null && <span className="faint">{pv.last_count} fetched</span>}
                <button className="sm" onClick={() => props.onRefreshProvider(pv)}>{t("tbl.refresh")}</button>
                <button className="sm ghost danger" onClick={() => props.onDeleteProvider(pv)}>✕</button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* get-proxies offers (affiliate) */}
      <div className="offers">
        <span className="offers-label">{t("offers.hint")}</span>
        <div className="offer-dd">
          <button className="primary sm" onClick={() => setOffersOpen((v) => !v)}>{t("offers.button")}</button>
          {offersOpen && <div className="dd-backdrop" onClick={() => setOffersOpen(false)} />}
          {offersOpen && (
            <div className="offer-menu">
              {PROXY_OFFERS.map((o) => (
                <a className="offer-item" key={o.href} href={o.href} onClick={(e) => { setOffersOpen(false); openExternal(e, o.href); }}>
                  <span className="offer-tier">{t(o.tierKey)}</span>
                  <img className="offer-logo" src={o.logo} alt={o.alt} />
                  <span className="offer-sub">{t(o.subKey)}</span>
                </a>
              ))}
              <div className="offer-disc">{t("offers.disclosure")}</div>
            </div>
          )}
        </div>
      </div>

      {/* pool table */}
      {props.proxies.length === 0 ? (
        <div className="empty">
          <div className="big">{t("pool.empty")}</div>
          {t("pool.emptyHint")}<br />
          <button className="primary" style={{ marginTop: 14 }} onClick={props.onAdd}>{t("tb.addProxy")}</button>
        </div>
      ) : (
        <table className="ptable">
          <thead>
            <tr><th></th><th>{t("tbl.label")}</th><th>{t("tbl.address")}</th><th>{t("tbl.status")}</th><th>{t("tbl.ipType")}</th><th>{t("tbl.source")}</th><th></th></tr>
          </thead>
          <tbody>
            {props.proxies.map((p) => (
              <tr key={p.id} style={{ opacity: p.enabled ? 1 : 0.5 }}>
                <td>
                  <span className={`toggle ${p.enabled ? "on" : ""}`} onClick={() => props.onToggle(p)} title={p.enabled ? "enabled" : "disabled"}>
                    <span className="knob" />
                  </span>
                </td>
                <td className="lbl">
                  {p.label}{p.group && <span className="chip grp" style={{ marginLeft: 6 }}>{p.group}</span>}
                  {p.note && <div className="faint" style={{ fontWeight: 400, fontSize: 11 }}>{p.note}</div>}
                </td>
                <td className="raw">{mask(p.raw)}</td>
                <td>
                  {p.last_ok === true ? (
                    <span className="geo-badge ok">● {p.last_ip} · {p.last_cc} · {p.last_tz}</span>
                  ) : p.last_ok === false ? (
                    <span className="geo-badge bad">● {t("pool.failed")} ×{p.fail_count}</span>
                  ) : (
                    <span className="geo-badge none">○ {t("pool.notChecked")}</span>
                  )}
                </td>
                <td>
                  {p.ip_type ? (
                    <span className={`iptype ${p.ip_type}`} title={p.isp ?? ""}>
                      {p.ip_type === "datacenter" ? t("ipt.datacenter") : p.ip_type === "residential" ? t("ipt.residential") : t("ipt.mobile")}
                    </span>
                  ) : <span className="faint" style={{ fontSize: 12 }}>—</span>}
                </td>
                <td className="faint" style={{ fontSize: 12 }}>{p.source ?? "manual"}</td>
                <td>
                  <div className="row-actions">
                    <button className="sm" onClick={() => props.onCheck(p)}>{t("tbl.test")}</button>
                    <button className="sm" onClick={() => props.onEdit(p)}>{t("card.edit")}</button>
                    <button className="sm ghost danger" onClick={() => props.onDelete(p)}>✕</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ProviderModal(props: {
  onClose: () => void; onSaved: (m: string) => void; onError: (m: string) => void;
}) {
  const t = useT();
  const [kind, setKind] = useState("api_extract");
  const [url, setUrl] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await api.addProvider(kind, url.trim(), label.trim() || undefined); props.onSaved("provider added"); }
    catch (e: any) { props.onError(e.message); }
    finally { setBusy(false); }
  };
  return (
    <div className="overlay" onClick={props.onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{t("pv.add")}</h2>
        <div className="desc">{t("pv.desc")}</div>
        <div className="field">
          <label>{t("pv.kind")}</label>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="api_extract">{t("pv.kindApi")}</option>
            <option value="rotating_gateway">{t("pv.kindGw")}</option>
          </select>
        </div>
        <div className="field">
          <label>{kind === "api_extract" ? t("pv.listUrl") : t("pv.gwAddr")}</label>
          <input value={url} onChange={(e) => setUrl(e.target.value)}
            placeholder={kind === "api_extract" ? "https://provider.com/api/proxies?token=…" : "socks5://user:pass@gw.provider.com:7000"} />
        </div>
        <div className="field">
          <label>{t("px.label")} <span className="hint">· {t("pv.labelHint")}</span></label>
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="provider01" />
        </div>
        <div className="foot">
          <button onClick={props.onClose}>{t("dlg.cancel")}</button>
          <button className="primary" onClick={save} disabled={busy || !url}>{busy ? t("pm.saving") : t("dlg.add")}</button>
        </div>
      </div>
    </div>
  );
}

// ---------------- profile modal ----------------
const NONE = "__none__";
const CUSTOM = "__custom__";

function ProfileModal(props: {
  profile: Profile | null; groups: Group[]; proxies: PoolProxy[];
  defaultGroup: string;
  onClose: () => void; onSaved: (m: string) => void; onError: (m: string) => void;
}) {
  const p = props.profile;
  const isNew = !p;
  const t = useT();
  const [name, setName] = useState(p?.name ?? "");
  const [os, setOs] = useState(p?.os ?? "macos");
  const [engine, setEngine] = useState(p?.engine ?? "camoufox");
  const [group, setGroup] = useState(p?.group ?? (props.defaultGroup || "default"));
  const [newGroup, setNewGroup] = useState("");
  const [note, setNote] = useState(p?.note ?? "");
  // proxy selection: pool id | NONE | CUSTOM
  const initialPool = props.proxies.find((x) => x.raw === p?.proxy_raw);
  const [proxySel, setProxySel] = useState<string>(
    p?.proxy_raw ? (initialPool ? initialPool.id : CUSTOM) : NONE
  );
  const [customProxy, setCustomProxy] = useState(initialPool ? "" : p?.proxy_raw ?? "");
  const [geo, setGeo] = useState<GeoInfo | null>(null);
  const [geoErr, setGeoErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // prefill an auto name for new profiles
  useEffect(() => {
    if (isNew) api.nextName().then((r) => setName((n) => n || r.name)).catch(() => {});
  }, [isNew]);

  const resolvedProxy = (): string | null => {
    if (proxySel === NONE) return null;
    if (proxySel === CUSTOM) return customProxy.trim() || null;
    return props.proxies.find((x) => x.id === proxySel)?.raw ?? null;
  };

  const testProxy = async () => {
    const raw = resolvedProxy();
    if (!raw) return;
    setBusy(true); setGeo(null); setGeoErr(null);
    try { setGeo(await api.checkProxy(raw)); }
    catch (e: any) { setGeoErr(e.message); }
    finally { setBusy(false); }
  };

  const save = async () => {
    setBusy(true);
    const grp = newGroup.trim() || group;
    try {
      if (newGroup.trim()) await api.addGroup(newGroup.trim());
      if (isNew) {
        await api.create({ name: name.trim() || undefined, os, engine, proxy: resolvedProxy(), group: grp, note });
        props.onSaved(`created ${name}`);
      } else {
        await api.update(p!.id, { name: name.trim(), proxy: resolvedProxy() ?? "", group: grp, note });
        props.onSaved(`updated ${name}`);
      }
    } catch (e: any) { props.onError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="overlay" onClick={props.onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{isNew ? t("pm.new") : t("pm.edit", p!.name)}</h2>
        <div className="desc">{t("pm.desc")}</div>

        <div className="field">
          <label>{t("pm.name")} <span className="hint">· {t("pm.nameHint")}</span></label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="xman01" />
        </div>

        <div className="inline">
          <div className="field" style={{ flex: 1 }}>
            <label>{t("pm.os")}</label>
            <select value={os} onChange={(e) => setOs(e.target.value)} disabled={!isNew}>
              <option value="macos">macOS</option>
              <option value="windows">Windows</option>
              <option value="linux">Linux</option>
            </select>
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label>{t("pm.engine")} {!isNew && <span className="hint">· {t("pm.fixed")}</span>}</label>
            <select value={engine} onChange={(e) => setEngine(e.target.value)} disabled={!isNew}>
              <option value="camoufox">{t("pm.camoufox")}</option>
              <option value="chromium">{t("pm.chromium")}</option>
            </select>
          </div>
        </div>
        {isNew && (
          <div className="hint" style={{ marginTop: -8, marginBottom: 14 }}>
            {engine === "camoufox" ? t("pm.camoufoxHint") : t("pm.chromiumHint")}
          </div>
        )}

        <div className="field">
          <label>{t("pm.group")}</label>
          <div className="inline">
            <select value={group} onChange={(e) => setGroup(e.target.value)}>
              {props.groups.map((g) => <option key={g.name} value={g.name}>{g.name}</option>)}
              {!props.groups.find((g) => g.name === group) && <option value={group}>{group}</option>}
            </select>
            <input style={{ flex: 1 }} placeholder={t("pm.newGroupPh")} value={newGroup} onChange={(e) => setNewGroup(e.target.value)} />
          </div>
        </div>

        <div className="field">
          <label>{t("card.proxy")} <span className="hint">· {t("pm.proxyHint")}</span></label>
          <select value={proxySel} onChange={(e) => { setProxySel(e.target.value); setGeo(null); setGeoErr(null); }}>
            <option value={NONE}>{t("pm.none")}</option>
            {props.proxies.map((x) => (
              <option key={x.id} value={x.id}>
                {x.label}{x.last_cc ? ` — ${x.last_cc}` : ""} ({x.raw.split("://")[0]})
              </option>
            ))}
            <option value={CUSTOM}>{t("pm.custom")}</option>
          </select>
          {proxySel === CUSTOM && (
            <div className="inline" style={{ marginTop: 8 }}>
              <input placeholder="socks5://user:pass@host:1080" value={customProxy} onChange={(e) => setCustomProxy(e.target.value)} />
              <button onClick={testProxy} disabled={busy || !customProxy}>{t("pm.test")}</button>
            </div>
          )}
          {proxySel !== CUSTOM && proxySel !== NONE && (
            <button className="sm" style={{ marginTop: 8, alignSelf: "flex-start" }} onClick={testProxy} disabled={busy}>{t("pm.testThis")}</button>
          )}
          {geo && <div className="geo ok">✓ exit <b>{geo.ip}</b> — {geo.city}, {geo.country} ({geo.country_code}) · {geo.timezone}</div>}
          {geoErr && <div className="geo bad">✗ {geoErr}</div>}
        </div>

        <div className="field">
          <label>{t("pm.note")}</label>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("pm.optional")} />
        </div>

        <div className="foot">
          <button onClick={props.onClose}>{t("dlg.cancel")}</button>
          <button className="primary" onClick={save} disabled={busy}>{busy ? t("pm.saving") : isNew ? t("pm.create") : t("pm.save")}</button>
        </div>
      </div>
    </div>
  );
}

// ---------------- proxy modal ----------------
function ProxyModal(props: {
  proxy: PoolProxy | null;
  onClose: () => void; onSaved: (m: string) => void; onError: (m: string) => void;
}) {
  const p = props.proxy;
  const isNew = !p;
  const t = useT();
  const [label, setLabel] = useState(p?.label ?? "");
  const [raw, setRaw] = useState(p?.raw ?? "");
  const [note, setNote] = useState(p?.note ?? "");
  const [group, setGroup] = useState(p?.group ?? "");
  const [geo, setGeo] = useState<GeoInfo | null>(null);
  const [geoErr, setGeoErr] = useState<string | null>(null);
  const [detected, setDetected] = useState<{ ok: boolean; error?: string; scheme?: string; host?: string; port?: number; has_auth?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  // Auto-detect the pasted proxy format (debounced) so the user sees what we parsed.
  useEffect(() => {
    const v = raw.trim();
    if (!v) { setDetected(null); return; }
    const timer = setTimeout(() => { api.parseProxy(v).then(setDetected).catch(() => {}); }, 250);
    return () => clearTimeout(timer);
  }, [raw]);

  const test = async () => {
    if (!raw) return;
    setBusy(true); setGeo(null); setGeoErr(null);
    try { setGeo(await api.checkProxy(raw)); }
    catch (e: any) { setGeoErr(e.message); }
    finally { setBusy(false); }
  };
  const save = async () => {
    setBusy(true);
    try {
      if (isNew) { await api.addProxy(raw.trim(), label.trim() || undefined, note, group.trim()); props.onSaved("proxy added"); }
      else { await api.updateProxy(p!.id, { label: label.trim(), raw: raw.trim(), note, group: group.trim() }); props.onSaved("proxy saved"); }
    } catch (e: any) { props.onError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="overlay" onClick={props.onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{isNew ? t("px.add") : t("px.edit", p!.label)}</h2>
        <div className="desc">{t("px.desc")}</div>
        <div className="field">
          <label>{t("px.label")} <span className="hint">· {t("px.labelHint")}</span></label>
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="proxy01" />
        </div>
        <div className="field">
          <label>{t("px.address")} <span className="hint">· {t("px.addressHint")}</span></label>
          <div className="inline">
            <input value={raw} onChange={(e) => setRaw(e.target.value)} placeholder="socks5://user:pass@host:1080  ·  host:port:user:pass  ·  http://host:8080" />
            <button onClick={test} disabled={busy || !raw}>{t("pm.test")}</button>
          </div>
          {detected && (detected.ok ? (
            <div className="detected ok">
              {t("px.detected")} <span className="tag">{detected.scheme}</span> {detected.host}:{detected.port}
              {detected.has_auth ? <span className="faint"> · {t("px.withAuth")}</span> : <span className="faint"> · {t("px.noAuth")}</span>}
            </div>
          ) : (
            <div className="detected bad">{t("px.unrecognized")}</div>
          ))}
          {geo && <div className="geo ok">✓ exit <b>{geo.ip}</b> — {geo.city}, {geo.country} ({geo.country_code}) · {geo.timezone}</div>}
          {geoErr && <div className="geo bad">✗ {geoErr}</div>}
        </div>
        <div className="inline">
          <div className="field" style={{ flex: 1 }}>
            <label>{t("pm.group")} <span className="hint">· {t("px.groupHint")}</span></label>
            <input value={group} onChange={(e) => setGroup(e.target.value)} placeholder={t("px.groupPh")} />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label>{t("pm.note")}</label>
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("pm.optional")} />
          </div>
        </div>
        <div className="foot">
          <button onClick={props.onClose}>{t("dlg.cancel")}</button>
          <button className="primary" onClick={save} disabled={busy || !raw}>{busy ? t("pm.saving") : isNew ? t("dlg.add") : t("pm.save")}</button>
        </div>
      </div>
    </div>
  );
}

// ---------------- bulk proxy import ----------------
function BulkProxyModal(props: {
  onClose: () => void; onDone: (added: number, skipped: number) => void; onError: (m: string) => void;
}) {
  const t = useT();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.addProxiesBulk(text);
      props.onDone(r.added.length, r.skipped);
    } catch (e: any) { props.onError(e.message); }
    finally { setBusy(false); }
  };
  return (
    <div className="overlay" onClick={props.onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{t("bulk.title")}</h2>
        <div className="desc">{t("bulk.desc")}</div>
        <div className="field">
          <textarea style={{ minHeight: 200, fontFamily: "ui-monospace, monospace", fontSize: 12 }}
            value={text} onChange={(e) => setText(e.target.value)}
            placeholder={"socks5://user:pass@1.2.3.4:1080\nhttp://gw.example.com:8080\n5.6.7.8:1080:user:pass\n\n# or paste docker ps output:\nnordvpn-th40-proxy  …  18893:8888  …"} />
        </div>
        <div className="foot">
          <button onClick={props.onClose}>{t("dlg.cancel")}</button>
          <button className="primary" onClick={submit} disabled={busy || !text.trim()}>{busy ? t("pm.saving") : t("bulk.import")}</button>
        </div>
      </div>
    </div>
  );
}

// ---------------- engine download progress ----------------
function EngineDownloadModal(props: { engine: string; onClose: () => void; onReady: () => void }) {
  const t = useT();
  const label = props.engine === "chromium" ? "Chrome" : "Camoufox (Firefox)";
  const approxMB = props.engine === "chromium" ? 500 : 380;
  const [st, setSt] = useState<EngineStatus | null>(null);
  const readyFired = useRef(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const all = await api.engineStatus();
        const s = all[props.engine];
        if (cancelled) return;
        setSt(s);
        if (s?.state === "ready" && !readyFired.current) {
          readyFired.current = true;
          props.onReady();
          return;
        }
      } catch { /* keep polling */ }
      if (!cancelled) timer = setTimeout(tick, 800);
    };
    tick();
    return () => { cancelled = true; clearTimeout(timer); };
  }, []); // eslint-disable-line

  const pct = st?.percent ?? 0;
  const err = st?.state === "error";
  return (
    <div className="overlay">
      <div className="modal" style={{ width: 420 }}>
        <h2>{t("eng.title", label)}</h2>
        <div className="desc">{t("eng.desc", label, approxMB)}</div>
        {err ? (
          <div className="geo bad" style={{ marginTop: 4 }}>{t("eng.failed", st?.message ?? "")}</div>
        ) : (
          <>
            <div className="progress"><div className="bar" style={{ width: `${Math.max(4, pct)}%` }} /></div>
            <div className="prog-row">
              <span>{t("eng.downloading")}</span>
              <span>{pct}%</span>
            </div>
          </>
        )}
        <div className="foot">
          <button onClick={props.onClose}>{err ? t("dlg.cancel") : t("eng.hide")}</button>
        </div>
      </div>
    </div>
  );
}

// ---------------- detail modal ----------------
function DetailModal({ p, onClose }: { p: Profile; onClose: () => void }) {
  const f = p.fingerprint;
  const rows: [string, any][] = [
    ["Name", p.name], ["Group", p.group], ["OS", p.os],
    ["User-Agent", f.userAgent], ["Platform", f.platform], ["Screen", f.screen],
    ["CPU cores", f.hardwareConcurrency], ["WebGL vendor", f.webglVendor],
    ["WebGL renderer", f.webglRenderer], ["Canvas offset", f.canvasOffset],
    ["Font seed", f.fontSpacingSeed], ["Proxy", p.proxy_raw ?? "none"],
    ["User-data-dir", p.user_data_dir ?? ""],
  ];
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{p.name}</h2>
        <div className="desc">Resolved fingerprint — stable across every launch of this profile.</div>
        <div className="kv">
          {rows.map(([k, v], i) => (
            <div key={i} style={{ display: "contents" }}>
              <div className="k">{k}</div>
              <div className="v">{String(v)}</div>
            </div>
          ))}
        </div>
        <div className="foot"><button className="primary" onClick={onClose}>Close</button></div>
      </div>
    </div>
  );
}
