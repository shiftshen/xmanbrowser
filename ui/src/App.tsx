import { useCallback, useEffect, useRef, useState } from "react";
import { api, GeoInfo, Profile } from "./api";

type Toast = { msg: string; err?: boolean } | null;

export function App() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [search, setSearch] = useState("");
  const [online, setOnline] = useState<boolean | null>(null);
  const [version, setVersion] = useState("");
  const [editing, setEditing] = useState<Profile | "new" | null>(null);
  const [detail, setDetail] = useState<Profile | null>(null);
  const [toast, setToast] = useState<Toast>(null);
  const [connErr, setConnErr] = useState<string>("");
  const fileRef = useRef<HTMLInputElement>(null);

  const flash = useCallback((msg: string, err = false) => {
    setToast({ msg, err });
    setTimeout(() => setToast(null), 2600);
  }, []);

  const refresh = useCallback(async (q = search) => {
    try {
      setProfiles(await api.list(q));
    } catch (e: any) {
      flash(e.message, true);
    }
  }, [search, flash]);

  // Continuously probe the backend. It can take a few seconds for the desktop
  // shell to spawn it on startup, so we KEEP polling until it answers (and flip
  // back to offline if it later disappears) instead of giving up after one try.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const h = await api.health();
        if (cancelled) return;
        setVersion(h.version);
        setOnline((was) => {
          if (!was) refresh(); // just (re)connected — load profiles
          return true;
        });
      } catch (e: any) {
        if (!cancelled) {
          setOnline(false);
          setConnErr(String(e?.message ?? e));
        }
      }
      if (!cancelled) timer = setTimeout(tick, 2000);
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

  return (
    <div className="app">
      <div className="topbar">
        <div className="logo">X<span>Man</span></div>
        <span className="muted">fingerprint browser {version && `v${version}`}</span>
        <div className="grow" />
        <span className="muted">
          <span className={`status-dot ${online ? "ok" : "bad"}`} />
          {online === null ? "connecting…" : online ? "API connected" : "API offline — run `xman serve`"}
        </span>
      </div>

      <div className="toolbar">
        <input
          className="search"
          placeholder="Search profiles…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            refresh(e.target.value);
          }}
        />
        <div className="grow" />
        <button onClick={() => fileRef.current?.click()}>Import</button>
        <button onClick={onExport}>Export</button>
        <button className="primary" onClick={() => setEditing("new")}>+ New profile</button>
        <input
          ref={fileRef}
          type="file"
          accept="application/json"
          style={{ display: "none" }}
          onChange={(e) => e.target.files?.[0] && onImportFile(e.target.files[0])}
        />
      </div>

      <div className="content">
        {!online ? (
          <div className="empty">
            Connecting to the local control service…
            <br />This starts automatically; it can take a few seconds on launch.
            {connErr && (
              <>
                <br />
                <span style={{ color: "#ff7b72", fontSize: 12 }}>last error: {connErr}</span>
              </>
            )}
          </div>
        ) : profiles.length === 0 ? (
          <div className="empty">No profiles yet. Click <b>+ New profile</b> to create one.</div>
        ) : (
          <div className="grid">
            {profiles.map((p) => (
              <ProfileCard
                key={p.id}
                p={p}
                onLaunch={() => act(() => api.launch(p.id), `launched ${p.name}`)}
                onStop={() => act(() => api.stop(p.id), `stopped ${p.name}`)}
                onEdit={() => setEditing(p)}
                onDetail={async () => setDetail(await api.get(p.id))}
                onClone={() => {
                  const n = prompt(`Clone "${p.name}" as:`, `${p.name}-copy`);
                  if (n) act(() => api.clone(p.id, n), "cloned");
                }}
                onDelete={() => {
                  if (confirm(`Delete "${p.name}" and its data?`)) act(() => api.remove(p.id), "deleted");
                }}
              />
            ))}
          </div>
        )}
      </div>

      {editing && (
        <ProfileModal
          profile={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(m) => {
            setEditing(null);
            flash(m);
            refresh();
          }}
          onError={(m) => flash(m, true)}
        />
      )}

      {detail && <DetailModal p={detail} onClose={() => setDetail(null)} />}
      {toast && <div className={`toast ${toast.err ? "err" : ""}`}>{toast.msg}</div>}
    </div>
  );
}

function ProfileCard(props: {
  p: Profile;
  onLaunch: () => void;
  onStop: () => void;
  onEdit: () => void;
  onDetail: () => void;
  onClone: () => void;
  onDelete: () => void;
}) {
  const { p } = props;
  const f = p.fingerprint;
  return (
    <div className="card">
      <div className="row">
        <span className="name">{p.name}</span>
        <span className="badge os">{p.os}</span>
        {p.running && <span className="badge run">● running</span>}
        <div className="grow" style={{ flex: 1 }} />
        {p.group !== "default" && <span className="badge">{p.group}</span>}
      </div>
      <div className="fp" onClick={props.onDetail} style={{ cursor: "pointer" }}>
        <div><b>{f.screen}</b> · {f.hardwareConcurrency} cores · {f.platform}</div>
        <div>WebGL: <b>{f.webglRenderer}</b></div>
        <div>Proxy: <b>{p.proxy_raw ?? "none (direct)"}</b></div>
        {p.note && <div className="muted">“{p.note}”</div>}
      </div>
      <div className="actions">
        {p.running ? (
          <button className="danger" onClick={props.onStop}>Stop</button>
        ) : (
          <button className="primary" onClick={props.onLaunch}>Launch</button>
        )}
        <button onClick={props.onEdit}>Edit</button>
        <button onClick={props.onClone}>Clone</button>
        <button className="ghost danger" onClick={props.onDelete}>Del</button>
      </div>
    </div>
  );
}

function ProfileModal(props: {
  profile: Profile | null;
  onClose: () => void;
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const p = props.profile;
  const isNew = !p;
  const [name, setName] = useState(p?.name ?? "");
  const [os, setOs] = useState(p?.os ?? "macos");
  const [proxy, setProxy] = useState(p?.proxy_raw ?? "");
  const [group, setGroup] = useState(p?.group ?? "default");
  const [note, setNote] = useState(p?.note ?? "");
  const [geo, setGeo] = useState<GeoInfo | null>(null);
  const [geoErr, setGeoErr] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);

  const check = async () => {
    if (!proxy) return;
    setChecking(true);
    setGeo(null);
    setGeoErr(null);
    try {
      setGeo(await api.checkProxy(proxy));
    } catch (e: any) {
      setGeoErr(e.message);
    } finally {
      setChecking(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      if (isNew) {
        await api.create({ name, os, proxy: proxy || null, group, note });
        props.onSaved(`created ${name}`);
      } else {
        await api.update(p!.id, { name, proxy: proxy || "", group, note });
        props.onSaved(`updated ${name}`);
      }
    } catch (e: any) {
      props.onError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="overlay" onClick={props.onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{isNew ? "New profile" : `Edit ${p!.name}`}</h2>
        <div className="field">
          <label>Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. account-eu-1" />
        </div>
        <div className="field">
          <label>Operating system {isNew ? "(drives the fingerprint)" : "(fixed after creation)"}</label>
          <select value={os} onChange={(e) => setOs(e.target.value)} disabled={!isNew}>
            <option value="macos">macOS</option>
            <option value="windows">Windows</option>
            <option value="linux">Linux</option>
          </select>
        </div>
        <div className="field">
          <label>Proxy (http / socks5) — timezone & locale auto-follow its exit IP</label>
          <div className="inline">
            <input
              value={proxy}
              onChange={(e) => setProxy(e.target.value)}
              placeholder="socks5://user:pass@host:1080"
            />
            <button onClick={check} disabled={!proxy || checking}>{checking ? "…" : "Test"}</button>
          </div>
          {geo && (
            <div className="geo ok">
              ✓ exit <b>{geo.ip}</b> — {geo.city}, {geo.country} ({geo.country_code}) · tz {geo.timezone}
            </div>
          )}
          {geoErr && <div className="geo bad">✗ {geoErr}</div>}
        </div>
        <div className="field">
          <label>Group</label>
          <input value={group} onChange={(e) => setGroup(e.target.value)} />
        </div>
        <div className="field">
          <label>Note</label>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <div className="foot">
          <button onClick={props.onClose}>Cancel</button>
          <button className="primary" onClick={save} disabled={!name || saving}>
            {saving ? "Saving…" : isNew ? "Create" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

function DetailModal({ p, onClose }: { p: Profile; onClose: () => void }) {
  const f = p.fingerprint;
  const rows: [string, any][] = [
    ["Name", p.name],
    ["OS", p.os],
    ["User-Agent", f.userAgent],
    ["Platform", f.platform],
    ["Screen", f.screen],
    ["CPU cores", f.hardwareConcurrency],
    ["WebGL vendor", f.webglVendor],
    ["WebGL renderer", f.webglRenderer],
    ["Canvas offset", f.canvasOffset],
    ["Font seed", f.fontSpacingSeed],
    ["Proxy", p.proxy_raw ?? "none"],
    ["User-data-dir", p.user_data_dir ?? ""],
  ];
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{p.name} — fingerprint</h2>
        <div className="kv">
          {rows.map(([k, v]) => (
            <>
              <div className="k">{k}</div>
              <div className="v">{String(v)}</div>
            </>
          ))}
        </div>
        <div className="foot">
          <button className="primary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
