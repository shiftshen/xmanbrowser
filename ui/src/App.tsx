import { useCallback, useEffect, useRef, useState } from "react";
import { api, DetectResult, EngineStatus, GeoInfo, Group, PoolProxy, Profile, Provider } from "./api";
import logoShield from "./assets/logo-shield.png";
import logo711 from "./assets/offers/711proxy.svg";
import logoWebshare from "./assets/offers/webshare.svg";

type Toast = { msg: string; err?: boolean } | null;
type View = "profiles" | "proxies";

// Proxy affiliate placements (referral links). Two picks: one premium /
// Chinese-payment-friendly, one budget with a free tier.
const PROXY_OFFERS: { tier: string; logo: string; alt: string; sub: string; href: string }[] = [
  { tier: "高质量住宅", logo: logo711, alt: "711Proxy", sub: "9000万+住宅IP · 中文/支付宝 · 抗风控", href: "https://www.711proxy.com/signup?code=812411" },
  { tier: "便宜入门", logo: logoWebshare, alt: "Webshare", sub: "免费10个代理起 · 按量计费 · 卡/PayPal", href: "https://www.webshare.io/?referral_code=a408k2bpaeid" },
];

// Affiliate CTA shown when a detection comes back dirty (→ buy clean proxies).
const CLEAN_IP_CTA = PROXY_OFFERS[0]; // 711Proxy

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
      const res = await api.launch(p.id, url);
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

  const onExport = async () => {
    const data = await api.exportAll();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "xman-profiles.json";
    a.click();
    flash(`exported ${data.length} profiles`);
  };
  const onImportFile = async (f: File) => {
    try {
      const data = JSON.parse(await f.text());
      const res = await api.importProfiles(Array.isArray(data) ? data : [data]);
      flash(`imported ${res.filter((r) => !r.error).length}`);
      refresh();
    } catch (e: any) {
      flash(e.message, true);
    }
  };

  const visible = profiles.filter((p) => !group || p.group === group);
  const addGroup = async () => {
    const n = prompt("New group name:");
    if (n?.trim()) act(() => api.addGroup(n.trim()), "group added");
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

        <div className="nav-label">Profiles</div>
        <div
          className={`nav-item ${view === "profiles" && !group ? "active" : ""}`}
          onClick={() => { setView("profiles"); setGroup(""); }}
        >
          <span className="ico">▦</span> All profiles
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
        <div className="nav-item nav-add" onClick={addGroup}><span className="ico">＋</span> New group</div>

        <div className="nav-label">Network</div>
        <div className={`nav-item ${view === "proxies" ? "active" : ""}`} onClick={() => setView("proxies")}>
          <span className="ico">⇄</span> Proxy pool
          <span className="grow" />
          <span className="count">{proxies.length}</span>
        </div>

        <div className="spacer" />
        <div className="api-pill">
          <span className={`dot ${online === null ? "wait" : online ? "ok" : "bad"}`} />
          {online === null ? "connecting…" : online ? `connected · v${version}` : "starting…"}
        </div>
      </aside>

      {/* ---------------- main ---------------- */}
      <div className="main">
        <div className="toolbar">
          {view === "profiles" ? (
            <h1>{group || "All profiles"} <span className="sub">{visible.length}</span></h1>
          ) : (
            <h1>Proxy pool <span className="sub">{proxies.length}</span></h1>
          )}
          <div className="grow" />
          {view === "profiles" ? (
            <>
              <input className="search" placeholder="Search…" value={search}
                onChange={(e) => { setSearch(e.target.value); }} />
              {(() => {
                const idle = visible.filter((p) => !p.running).map((p) => p.id);
                const live = visible.filter((p) => p.running).map((p) => p.id);
                return (
                  <>
                    {idle.length > 0 && (
                      <button title={`Launch ${idle.length}`} onClick={() => act(() => api.batchLaunch(idle), `launching ${idle.length}`)}>▶ Launch all</button>
                    )}
                    {live.length > 0 && (
                      <button className="danger" title={`Stop ${live.length}`} onClick={() => act(() => api.batchStop(live), `stopping ${live.length}`)}>■ Stop all</button>
                    )}
                  </>
                );
              })()}
              <button onClick={() => fileRef.current?.click()}>Import</button>
              <button onClick={onExport}>Export</button>
              <button className="primary" onClick={() => setEditing("new")}>＋ New profile</button>
              <input ref={fileRef} type="file" accept="application/json" style={{ display: "none" }}
                onChange={(e) => e.target.files?.[0] && onImportFile(e.target.files[0])} />
            </>
          ) : (
            <>
              <button onClick={() => act(() => api.checkAllProxies(), "tested all")} disabled={proxies.length === 0}>Test all</button>
              <button onClick={() => setBulkOpen(true)}>Bulk import</button>
              <button className="primary" onClick={() => setEditingProxy("new")}>＋ Add proxy</button>
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
          ) : view === "proxies" ? (
            <ProxiesView
              proxies={proxies}
              providers={providers}
              onAdd={() => setEditingProxy("new")}
              onEdit={(p) => setEditingProxy(p)}
              onCheck={(p) => act(() => api.checkPoolProxy(p.id), "checked")}
              onToggle={(p) => act(() => api.setProxyEnabled(p.id, !p.enabled))}
              onDelete={(p) => confirm(`Delete proxy "${p.label}"?`) && act(() => api.deleteProxy(p.id), "deleted")}
              onAddProvider={() => setEditingProvider(true)}
              onRefreshProvider={(pv) => act(() => api.refreshProvider(pv.id), "refreshed from provider")}
              onDeleteProvider={(pv) => confirm(`Delete provider "${pv.label}"?`) && act(() => api.deleteProvider(pv.id), "deleted")}
            />
          ) : visible.length === 0 ? (
            <div className="empty">
              <div className="big">No profiles {group ? `in “${group}”` : "yet"}</div>
              Click <b>＋ New profile</b> to create one — it gets an auto name and a fresh fingerprint.
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
                  onDelete={() => confirm(`Delete "${p.name}" and its data?`) && act(() => api.remove(p.id), "deleted")}
                />
              ))}
            </div>
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
            const url = engineDl.url;
            setEngineDl(null);
            try { await api.launch(id, url); flash("launched"); refresh(); }
            catch (e: any) { flash(e.message, true); }
          }}
        />
      )}
      {toast && <div className={`toast ${toast.err ? "err" : ""}`}>{toast.msg}</div>}
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
  const f = p.fingerprint;
  const pool = props.proxies.find((x) => x.raw === p.proxy_raw);
  const proxyOk = pool?.last_ok;
  return (
    <div className="card">
      <div className="head">
        <div className="avatar" style={{ background: avatarColor(p.name) }}>{initials(p.name)}</div>
        <span className="title">{p.name}</span>
        <span className="chip" title={p.engine === "chromium" ? "Chromium (patchright)" : "Camoufox (Firefox)"}>{p.engine === "chromium" ? "Chrome" : "Firefox"}</span>
        <span className="grow" />
        {p.running && <span className="chip run">running</span>}
      </div>
      <div className="specs" onClick={props.onDetail} style={{ cursor: "pointer" }}>
        <div className="line"><span className="k">System</span><b style={{ textTransform: "capitalize" }}>{p.os}</b> · {f.screen} · {f.hardwareConcurrency} cores</div>
        <div className="line"><span className="k">WebGL</span><b>{f.webglRenderer}</b></div>
        <div className="line"><span className="k">Proxy</span>
          {p.proxy_raw ? (
            <span className="proxy-tag">
              <span className="pdot" style={{ background: proxyOk === true ? "#3fb950" : proxyOk === false ? "#f0533f" : "#5c6678" }} />
              <b>{pool ? pool.label : p.proxy_raw}</b>
              {pool?.last_cc && <span className="faint">· {pool.last_cc}</span>}
            </span>
          ) : <b className="faint">none (direct)</b>}
        </div>
        {p.note && <div className="note">“{p.note}”</div>}
      </div>
      <div className="row" style={{ display: "flex", gap: 6 }}>
        {p.group !== "default" && <span className="chip grp">{p.group}</span>}
      </div>
      <div className="actions">
        {p.running
          ? <button className="danger" onClick={props.onStop}>Stop</button>
          : <button className="primary" onClick={props.onLaunch}>Launch</button>}
        <button className="sm" onClick={props.onEdit}>Edit</button>
        <button className="sm" onClick={props.onClone}>Clone</button>
        <button className="sm ghost danger iconbtn" onClick={props.onDelete}>✕</button>
      </div>
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
  const [detecting, setDetecting] = useState(false);
  const [detResult, setDetResult] = useState<DetectResult | null>(null);
  const [detErr, setDetErr] = useState<string | null>(null);
  const mask = (raw: string) => raw.replace(/:([^:@/]+)@/, ":••••@");

  const runDetect = async () => {
    setDetecting(true); setDetErr(null);
    try { setDetResult(await api.detect()); }
    catch (e: any) { setDetErr(e.message || "检测失败"); }
    finally { setDetecting(false); }
  };
  const ratingLabel = (r: string) => r === "clean" ? "干净" : r === "risky" ? "有风险" : "已被标记";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
      {/* one-click environment detection */}
      <div className="detect-panel">
        <div className="detect-head">
          <span className="sec-title">环境检测 <span className="faint">· 当前出口 IP 是否干净</span></span>
          <button className="primary" disabled={detecting} onClick={runDetect}>
            {detecting ? "检测中…" : "一键检测"}
          </button>
        </div>
        <div className="detect-hint">查当前网络出口 IP 的地区 · ISP · 类型 · 风控标记,给出 0–100 信任分。</div>
        {detErr && <div className="detect-err">检测失败:{detErr}</div>}
        {detResult && (
          <div className="detect-result">
            <div className={`score-badge ${detResult.rating}`}>
              <span className="score-num">{detResult.score}</span>
              <span className="score-label">{ratingLabel(detResult.rating)}</span>
            </div>
            <div className="detect-rows">
              {detResult.rows.map((r, i) => (
                <div className="detect-row" key={i}>
                  <span className={`drow-dot ${r.ok === false ? "bad" : r.ok === true ? "good" : "unk"}`} />
                  <span className="drow-k">{r.label}</span>
                  <span className="drow-v">{r.value}</span>
                </div>
              ))}
              {detResult.rating !== "clean" && (
                <a className="detect-cta" href={CLEAN_IP_CTA.href} target="_blank" rel="noreferrer">
                  IP 不够干净?换 711Proxy 住宅 IP →
                </a>
              )}
            </div>
          </div>
        )}
      </div>

      {/* providers panel */}
      <div className="providers">
        <div className="providers-head">
          <span className="sec-title">Providers <span className="faint">· auto-fetch proxies from an API or rotating gateway</span></span>
          <button className="sm primary" onClick={props.onAddProvider}>＋ Add provider</button>
        </div>
        {props.providers.length === 0 ? (
          <div className="faint" style={{ fontSize: 12.5, padding: "4px 2px" }}>
            No providers. Add one to pull proxies automatically instead of pasting them.
          </div>
        ) : (
          <div className="prov-list">
            {props.providers.map((pv) => (
              <div className="prov" key={pv.id}>
                <span className="chip">{pv.kind === "api_extract" ? "API" : "gateway"}</span>
                <b>{pv.label}</b>
                <span className="raw" style={{ flex: 1 }}>{pv.url}</span>
                {pv.last_count != null && <span className="faint">{pv.last_count} fetched</span>}
                <button className="sm" onClick={() => props.onRefreshProvider(pv)}>Refresh</button>
                <button className="sm ghost danger" onClick={() => props.onDeleteProvider(pv)}>✕</button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* get-proxies offers (affiliate) */}
      <div className="offers">
        <span className="offers-label">Need clean IPs? Datacenter/VPN IPs get flagged — residential & 4G pass anti-fraud.</span>
        <div className="offer-dd">
          <button className="primary sm" onClick={() => setOffersOpen((v) => !v)}>获取住宅 / 4G / ISP 代理 ▾</button>
          {offersOpen && <div className="dd-backdrop" onClick={() => setOffersOpen(false)} />}
          {offersOpen && (
            <div className="offer-menu">
              {PROXY_OFFERS.map((o) => (
                <a className="offer-item" key={o.href} href={o.href} target="_blank" rel="noreferrer" onClick={() => setOffersOpen(false)}>
                  <span className="offer-tier">{o.tier}</span>
                  <img className="offer-logo" src={o.logo} alt={o.alt} />
                  <span className="offer-sub">{o.sub}</span>
                </a>
              ))}
              <div className="offer-disc">Affiliate links — buying through them supports development.</div>
            </div>
          )}
        </div>
      </div>

      {/* pool table */}
      {props.proxies.length === 0 ? (
        <div className="empty">
          <div className="big">Your proxy pool is empty</div>
          Add proxies manually, paste many via Bulk import, or attach a provider above.<br />
          <button className="primary" style={{ marginTop: 14 }} onClick={props.onAdd}>＋ Add proxy</button>
        </div>
      ) : (
        <table className="ptable">
          <thead>
            <tr><th></th><th>Label</th><th>Address</th><th>Status</th><th>IP type</th><th>Source</th><th></th></tr>
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
                    <span className="geo-badge bad">● failed ×{p.fail_count}</span>
                  ) : (
                    <span className="geo-badge none">○ not checked</span>
                  )}
                </td>
                <td>
                  {p.ip_type ? (
                    <span className={`iptype ${p.ip_type}`} title={p.isp ?? ""}>
                      {p.ip_type === "datacenter" ? "Datacenter" : p.ip_type === "residential" ? "Residential" : "Mobile"}
                    </span>
                  ) : <span className="faint" style={{ fontSize: 12 }}>—</span>}
                </td>
                <td className="faint" style={{ fontSize: 12 }}>{p.source ?? "manual"}</td>
                <td>
                  <div className="row-actions">
                    <button className="sm" onClick={() => props.onCheck(p)}>Test</button>
                    <button className="sm" onClick={() => props.onEdit(p)}>Edit</button>
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
        <h2>Add proxy provider</h2>
        <div className="desc">Pull proxies automatically. <b>API</b> fetches a list from a URL (JSON or one-per-line); <b>Gateway</b> is a single rotating endpoint.</div>
        <div className="field">
          <label>Kind</label>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="api_extract">API extract (fetch a proxy list)</option>
            <option value="rotating_gateway">Rotating gateway (single endpoint)</option>
          </select>
        </div>
        <div className="field">
          <label>{kind === "api_extract" ? "List URL" : "Gateway address"}</label>
          <input value={url} onChange={(e) => setUrl(e.target.value)}
            placeholder={kind === "api_extract" ? "https://provider.com/api/proxies?token=…" : "socks5://user:pass@gw.provider.com:7000"} />
        </div>
        <div className="field">
          <label>Label <span className="hint">· auto (provider01) if empty</span></label>
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="provider01" />
        </div>
        <div className="foot">
          <button onClick={props.onClose}>Cancel</button>
          <button className="primary" onClick={save} disabled={busy || !url}>{busy ? "Adding…" : "Add"}</button>
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
        <h2>{isNew ? "New profile" : `Edit ${p!.name}`}</h2>
        <div className="desc">An isolated browser environment with its own fingerprint, proxy and storage.</div>

        <div className="field">
          <label>Name <span className="hint">· auto-generated, editable</span></label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="xman01" />
        </div>

        <div className="inline">
          <div className="field" style={{ flex: 1 }}>
            <label>Operating system</label>
            <select value={os} onChange={(e) => setOs(e.target.value)} disabled={!isNew}>
              <option value="macos">macOS</option>
              <option value="windows">Windows</option>
              <option value="linux">Linux</option>
            </select>
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label>Engine {!isNew && <span className="hint">· fixed</span>}</label>
            <select value={engine} onChange={(e) => setEngine(e.target.value)} disabled={!isNew}>
              <option value="camoufox">Camoufox · unique fingerprint (recommended)</option>
              <option value="chromium">Chromium · real Chrome, shared fingerprint</option>
            </select>
          </div>
        </div>
        {isNew && (
          <div className="hint" style={{ marginTop: -8, marginBottom: 14 }}>
            {engine === "camoufox"
              ? "Firefox-based, engine-level spoofing — each profile gets a unique WebGL/canvas/font fingerprint."
              : "Real Chrome via patchright (no automation tells). Profiles share the machine's hardware fingerprint; differ by UA / cookies / proxy."}
          </div>
        )}

        <div className="field">
          <label>Group</label>
          <div className="inline">
            <select value={group} onChange={(e) => setGroup(e.target.value)}>
              {props.groups.map((g) => <option key={g.name} value={g.name}>{g.name}</option>)}
              {!props.groups.find((g) => g.name === group) && <option value={group}>{group}</option>}
            </select>
            <input style={{ flex: 1 }} placeholder="or new group…" value={newGroup} onChange={(e) => setNewGroup(e.target.value)} />
          </div>
        </div>

        <div className="field">
          <label>Proxy <span className="hint">· timezone & locale auto-follow its exit IP</span></label>
          <select value={proxySel} onChange={(e) => { setProxySel(e.target.value); setGeo(null); setGeoErr(null); }}>
            <option value={NONE}>None (direct connection)</option>
            {props.proxies.map((x) => (
              <option key={x.id} value={x.id}>
                {x.label}{x.last_cc ? ` — ${x.last_cc}` : ""} ({x.raw.split("://")[0]})
              </option>
            ))}
            <option value={CUSTOM}>Custom (one-off)…</option>
          </select>
          {proxySel === CUSTOM && (
            <div className="inline" style={{ marginTop: 8 }}>
              <input placeholder="socks5://user:pass@host:1080" value={customProxy} onChange={(e) => setCustomProxy(e.target.value)} />
              <button onClick={testProxy} disabled={busy || !customProxy}>Test</button>
            </div>
          )}
          {proxySel !== CUSTOM && proxySel !== NONE && (
            <button className="sm" style={{ marginTop: 8, alignSelf: "flex-start" }} onClick={testProxy} disabled={busy}>Test this proxy</button>
          )}
          {geo && <div className="geo ok">✓ exit <b>{geo.ip}</b> — {geo.city}, {geo.country} ({geo.country_code}) · {geo.timezone}</div>}
          {geoErr && <div className="geo bad">✗ {geoErr}</div>}
        </div>

        <div className="field">
          <label>Note</label>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="optional" />
        </div>

        <div className="foot">
          <button onClick={props.onClose}>Cancel</button>
          <button className="primary" onClick={save} disabled={busy}>{busy ? "Saving…" : isNew ? "Create" : "Save"}</button>
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
    const t = setTimeout(() => { api.parseProxy(v).then(setDetected).catch(() => {}); }, 250);
    return () => clearTimeout(t);
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
        <h2>{isNew ? "Add proxy" : `Edit ${p!.label}`}</h2>
        <div className="desc">Saved to the pool — reuse it across profiles by name.</div>
        <div className="field">
          <label>Label <span className="hint">· auto (proxy01) if empty</span></label>
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="proxy01" />
        </div>
        <div className="field">
          <label>Address <span className="hint">· paste any format — auto-detected</span></label>
          <div className="inline">
            <input value={raw} onChange={(e) => setRaw(e.target.value)} placeholder="socks5://user:pass@host:1080  ·  host:port:user:pass  ·  http://host:8080" />
            <button onClick={test} disabled={busy || !raw}>Test</button>
          </div>
          {detected && (detected.ok ? (
            <div className="detected ok">
              detected <span className="tag">{detected.scheme}</span> {detected.host}:{detected.port}
              {detected.has_auth ? <span className="faint"> · with auth</span> : <span className="faint"> · no auth</span>}
            </div>
          ) : (
            <div className="detected bad">unrecognized format — use scheme://host:port, host:port:user:pass, or host:port</div>
          ))}
          {geo && <div className="geo ok">✓ exit <b>{geo.ip}</b> — {geo.city}, {geo.country} ({geo.country_code}) · {geo.timezone}</div>}
          {geoErr && <div className="geo bad">✗ {geoErr}</div>}
        </div>
        <div className="inline">
          <div className="field" style={{ flex: 1 }}>
            <label>Group <span className="hint">· optional tag</span></label>
            <input value={group} onChange={(e) => setGroup(e.target.value)} placeholder="e.g. us, residential" />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label>Note</label>
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="optional" />
          </div>
        </div>
        <div className="foot">
          <button onClick={props.onClose}>Cancel</button>
          <button className="primary" onClick={save} disabled={busy || !raw}>{busy ? "Saving…" : isNew ? "Add" : "Save"}</button>
        </div>
      </div>
    </div>
  );
}

// ---------------- bulk proxy import ----------------
function BulkProxyModal(props: {
  onClose: () => void; onDone: (added: number, skipped: number) => void; onError: (m: string) => void;
}) {
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
        <h2>Bulk import proxies</h2>
        <div className="desc">
          Paste proxies (one per line) — or paste raw <code>docker ps</code> output and
          we'll pull the port mappings out. Formats: <code>scheme://user:pass@host:port</code>,
          <code>host:port:user:pass</code>, <code>host:port</code>, or a <code>PORT:8888</code> mapping.
          Non-proxy lines are ignored; duplicates are skipped.
        </div>
        <div className="field">
          <textarea style={{ minHeight: 200, fontFamily: "ui-monospace, monospace", fontSize: 12 }}
            value={text} onChange={(e) => setText(e.target.value)}
            placeholder={"socks5://user:pass@1.2.3.4:1080\nhttp://gw.example.com:8080\n5.6.7.8:1080:user:pass\n\n# or paste docker ps output:\nnordvpn-th40-proxy  …  18893:8888  …"} />
        </div>
        <div className="foot">
          <button onClick={props.onClose}>Cancel</button>
          <button className="primary" onClick={submit} disabled={busy || !text.trim()}>{busy ? "Importing…" : "Import"}</button>
        </div>
      </div>
    </div>
  );
}

// ---------------- engine download progress ----------------
function EngineDownloadModal(props: { engine: string; onClose: () => void; onReady: () => void }) {
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
        <h2>Preparing the {label} engine</h2>
        <div className="desc">
          First time only — Xbrowser is downloading the {label} browser engine (~{approxMB}MB).
          This is a one-time setup; it's instant afterward. Keep the app open.
        </div>
        {err ? (
          <div className="geo bad" style={{ marginTop: 4 }}>
            Download failed: {st?.message}. Check your network and try Launch again.
          </div>
        ) : (
          <>
            <div className="progress"><div className="bar" style={{ width: `${Math.max(4, pct)}%` }} /></div>
            <div className="prog-row">
              <span>{st?.state === "ready" ? "Finishing…" : "Downloading…"}</span>
              <span>{pct}%</span>
            </div>
          </>
        )}
        <div className="foot">
          <button onClick={props.onClose}>{err ? "Close" : "Hide"}</button>
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
