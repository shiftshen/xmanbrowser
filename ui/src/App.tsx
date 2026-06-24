import { useCallback, useEffect, useRef, useState } from "react";
import { api, GeoInfo, Group, PoolProxy, Profile } from "./api";

type Toast = { msg: string; err?: boolean } | null;
type View = "profiles" | "proxies";

const AVATAR_COLORS = ["#4f8cff", "#7b5cff", "#3fb950", "#d6a338", "#f0533f", "#27b3b3", "#e06cc8"];
function avatarColor(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}
const initials = (s: string) => s.replace(/[^a-zA-Z0-9]/g, "").slice(0, 2).toUpperCase() || "·";

export function App() {
  const [view, setView] = useState<View>("profiles");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [proxies, setProxies] = useState<PoolProxy[]>([]);
  const [group, setGroup] = useState<string>(""); // "" = all
  const [search, setSearch] = useState("");
  const [online, setOnline] = useState<boolean | null>(null);
  const [version, setVersion] = useState("");
  const [connErr, setConnErr] = useState("");
  const [editing, setEditing] = useState<Profile | "new" | null>(null);
  const [editingProxy, setEditingProxy] = useState<PoolProxy | "new" | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [detail, setDetail] = useState<Profile | null>(null);
  const [toast, setToast] = useState<Toast>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const flash = useCallback((msg: string, err = false) => {
    setToast({ msg, err });
    setTimeout(() => setToast(null), 2600);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [ps, gs, px] = await Promise.all([api.list(search), api.groups(), api.proxies()]);
      setProfiles(ps);
      setGroups(gs);
      setProxies(px);
    } catch (e: any) {
      flash(e.message, true);
    }
  }, [search, flash]);

  // poll backend until reachable; keep badges live
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const h = await api.health();
        if (cancelled) return;
        setVersion(h.version);
        setOnline((was) => {
          if (!was) refresh();
          return true;
        });
        await refresh();
      } catch (e: any) {
        if (!cancelled) {
          setOnline(false);
          setConnErr(String(e?.message ?? e));
        }
      }
      if (!cancelled) timer = setTimeout(tick, 2500);
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
          <div className="mark">X</div>
          <div className="name">X<span>Man</span></div>
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
              <button onClick={() => fileRef.current?.click()}>Import</button>
              <button onClick={onExport}>Export</button>
              <button className="primary" onClick={() => setEditing("new")}>＋ New profile</button>
              <input ref={fileRef} type="file" accept="application/json" style={{ display: "none" }}
                onChange={(e) => e.target.files?.[0] && onImportFile(e.target.files[0])} />
            </>
          ) : (
            <>
              <button onClick={() => setBulkOpen(true)}>Bulk import</button>
              <button className="primary" onClick={() => setEditingProxy("new")}>＋ Add proxy</button>
            </>
          )}
        </div>

        <div className="content">
          {!online ? (
            <div className="empty">
              <div className="big">Connecting to the local engine…</div>
              This starts automatically and can take a few seconds on launch.
              {connErr && <div style={{ color: "#ff8a7d", fontSize: 12, marginTop: 8 }}>last error: {connErr}</div>}
            </div>
          ) : view === "proxies" ? (
            <ProxiesView
              proxies={proxies}
              onAdd={() => setEditingProxy("new")}
              onEdit={(p) => setEditingProxy(p)}
              onCheck={(p) => act(() => api.checkPoolProxy(p.id), "checked")}
              onDelete={(p) => confirm(`Delete proxy "${p.label}"?`) && act(() => api.deleteProxy(p.id), "deleted")}
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
                  onLaunch={() => act(() => api.launch(p.id), `launched ${p.name}`)}
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
      {bulkOpen && (
        <BulkProxyModal
          onClose={() => setBulkOpen(false)}
          onDone={(n, errs) => { setBulkOpen(false); flash(errs ? `added ${n}, ${errs} failed` : `added ${n} proxies`); refresh(); }}
          onError={(m) => flash(m, true)}
        />
      )}
      {detail && <DetailModal p={detail} onClose={() => setDetail(null)} />}
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
  proxies: PoolProxy[];
  onAdd: () => void; onEdit: (p: PoolProxy) => void;
  onCheck: (p: PoolProxy) => void; onDelete: (p: PoolProxy) => void;
}) {
  if (props.proxies.length === 0)
    return (
      <div className="empty">
        <div className="big">Your proxy pool is empty</div>
        Add proxies once, then pick them by name when creating profiles.<br />
        <button className="primary" style={{ marginTop: 14 }} onClick={props.onAdd}>＋ Add proxy</button>
      </div>
    );
  const mask = (raw: string) => raw.replace(/:([^:@/]+)@/, ":••••@");
  return (
    <table className="ptable">
      <thead>
        <tr><th>Label</th><th>Address</th><th>Status</th><th></th></tr>
      </thead>
      <tbody>
        {props.proxies.map((p) => (
          <tr key={p.id}>
            <td className="lbl">{p.label}{p.note && <div className="faint" style={{ fontWeight: 400, fontSize: 11 }}>{p.note}</div>}</td>
            <td className="raw">{mask(p.raw)}</td>
            <td>
              {p.last_ok === true ? (
                <span className="geo-badge ok">● {p.last_ip} · {p.last_cc} · {p.last_tz}</span>
              ) : p.last_ok === false ? (
                <span className="geo-badge bad">● failed</span>
              ) : (
                <span className="geo-badge none">○ not checked</span>
              )}
            </td>
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
        await api.create({ name: name.trim() || undefined, os, proxy: resolvedProxy(), group: grp, note });
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

        <div className="field">
          <label>Operating system {isNew ? <span className="hint">· drives the fingerprint</span> : <span className="hint">· fixed after creation</span>}</label>
          <select value={os} onChange={(e) => setOs(e.target.value)} disabled={!isNew}>
            <option value="macos">macOS</option>
            <option value="windows">Windows</option>
            <option value="linux">Linux</option>
          </select>
        </div>

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
  const [geo, setGeo] = useState<GeoInfo | null>(null);
  const [geoErr, setGeoErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
      if (isNew) { await api.addProxy(raw.trim(), label.trim() || undefined, note); props.onSaved("proxy added"); }
      else { await api.updateProxy(p!.id, { label: label.trim(), raw: raw.trim(), note }); props.onSaved("proxy saved"); }
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
          <label>Address (http / socks5)</label>
          <div className="inline">
            <input value={raw} onChange={(e) => setRaw(e.target.value)} placeholder="socks5://user:pass@host:1080" />
            <button onClick={test} disabled={busy || !raw}>Test</button>
          </div>
          {geo && <div className="geo ok">✓ exit <b>{geo.ip}</b> — {geo.city}, {geo.country} ({geo.country_code}) · {geo.timezone}</div>}
          {geoErr && <div className="geo bad">✗ {geoErr}</div>}
        </div>
        <div className="field">
          <label>Note</label>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="optional" />
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
  onClose: () => void; onDone: (added: number, errors: number) => void; onError: (m: string) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const lines = text.split("\n").filter((l) => l.trim() && !l.trim().startsWith("#")).length;
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.addProxiesBulk(text);
      props.onDone(r.added.length, r.errors.length);
    } catch (e: any) { props.onError(e.message); }
    finally { setBusy(false); }
  };
  return (
    <div className="overlay" onClick={props.onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Bulk import proxies</h2>
        <div className="desc">One proxy per line. Formats: <code>scheme://user:pass@host:port</code>, <code>host:port:user:pass</code>, or <code>host:port</code>. Blank / # lines are ignored.</div>
        <div className="field">
          <textarea style={{ minHeight: 180, fontFamily: "ui-monospace, monospace", fontSize: 12 }}
            value={text} onChange={(e) => setText(e.target.value)}
            placeholder={"socks5://user:pass@1.2.3.4:1080\nhttp://gw.example.com:8080\n5.6.7.8:1080:user:pass"} />
        </div>
        <div className="foot">
          <span className="faint" style={{ marginRight: "auto", alignSelf: "center" }}>{lines} line{lines === 1 ? "" : "s"}</span>
          <button onClick={props.onClose}>Cancel</button>
          <button className="primary" onClick={submit} disabled={busy || !lines}>{busy ? "Importing…" : `Import ${lines}`}</button>
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
