"""Local FastAPI control service (M2).

Exposes REST endpoints for the UI (M3) to manage profiles, proxies, and running
browser instances. Binds to 127.0.0.1 only — this is a local-first app, not a
network service.

Run:  xman serve         (or)   uvicorn xman.service:app
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import store, manager, engine
from . import fingerprint as fp
from .proxy import Proxy, check_and_locate


@asynccontextmanager
async def _lifespan(app: FastAPI):
    store.init(migrate=True)
    yield


app = FastAPI(
    title="XMan",
    version="0.2.0",
    description="Open-source fingerprint browser — local control API",
    lifespan=_lifespan,
)

# UI (Tauri/Vite dev) runs on a different origin; allow localhost during dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- schemas ----------

class CreateProfile(BaseModel):
    name: Optional[str] = None  # auto-generated (xman01, …) when omitted
    os: str = "macos"
    engine: str = "camoufox"    # camoufox (Firefox) | chromium (patchright)
    proxy: Optional[str] = None
    group: str = "default"
    note: str = ""
    seed: Optional[int] = None


class ProxyIn(BaseModel):
    raw: str
    label: Optional[str] = None
    note: str = ""
    group: str = ""


class ProxyPatch(BaseModel):
    raw: Optional[str] = None
    label: Optional[str] = None
    note: Optional[str] = None
    group: Optional[str] = None


class GroupIn(BaseModel):
    name: str


class UpdateProfile(BaseModel):
    name: Optional[str] = None
    proxy: Optional[str] = None
    group: Optional[str] = None
    note: Optional[str] = None


class LaunchReq(BaseModel):
    url: str = "about:blank"
    headless: bool = False


def _view(prof) -> dict:
    return {
        **{k: v for k, v in prof.to_dict().items() if k != "fingerprint"},
        "os": prof.fingerprint.os,
        "engine": prof.fingerprint.engine,
        "fingerprint": fp.summary(prof.fingerprint),
        "running": manager.is_running(prof.id),
    }


# ---------- profiles ----------

@app.get("/api/health")
def health():
    return {"ok": True, "service": "xman", "version": app.version}


@app.get("/api/profiles")
def list_profiles(group: Optional[str] = None, search: Optional[str] = None):
    return [_view(p) for p in store.all_profiles(group=group, search=search)]


@app.post("/api/profiles", status_code=201)
def create_profile(body: CreateProfile):
    try:
        prof = store.create(body.name, os_name=body.os, engine=body.engine, proxy_raw=body.proxy,
                            group=body.group, note=body.note, seed=body.seed)
    except Exception as e:
        raise HTTPException(400, str(e))
    return _view(prof)


@app.get("/api/profiles/{name_or_id}")
def get_profile(name_or_id: str):
    try:
        prof = store.get(name_or_id)
    except KeyError:
        raise HTTPException(404, "profile not found")
    out = _view(prof)
    out["fingerprint_full"] = prof.fingerprint.to_dict()
    out["user_data_dir"] = str(prof.user_data_dir)
    return out


@app.patch("/api/profiles/{name_or_id}")
def update_profile(name_or_id: str, body: UpdateProfile):
    try:
        prof = store.update(
            name_or_id,
            proxy_raw=body.proxy if body.proxy is not None else ...,
            group=body.group if body.group is not None else ...,
            note=body.note if body.note is not None else ...,
            name=body.name if body.name is not None else ...,
        )
    except KeyError:
        raise HTTPException(404, "profile not found")
    except Exception as e:
        raise HTTPException(400, str(e))
    return _view(prof)


@app.delete("/api/profiles/{name_or_id}", status_code=204)
def delete_profile(name_or_id: str):
    try:
        manager.stop(store.get(name_or_id).id)
        store.delete(name_or_id)
    except KeyError:
        raise HTTPException(404, "profile not found")


@app.post("/api/profiles/{name_or_id}/clone")
def clone_profile(name_or_id: str, new_name: str, regenerate_fingerprint: bool = True):
    try:
        prof = store.clone(name_or_id, new_name, regenerate_fingerprint=regenerate_fingerprint)
    except KeyError:
        raise HTTPException(404, "profile not found")
    except Exception as e:
        raise HTTPException(400, str(e))
    return _view(prof)


# ---------- launch / stop ----------

@app.get("/api/engine/status")
def engine_status():
    return engine.status_all()


@app.post("/api/engine/{name}/ensure")
def engine_ensure(name: str):
    return engine.ensure_async(name)


@app.post("/api/profiles/{name_or_id}/launch")
def launch_profile(name_or_id: str, body: LaunchReq, response: Response):
    try:
        prof = store.get(name_or_id)
    except KeyError:
        raise HTTPException(404, "profile not found")
    eng = prof.fingerprint.engine
    # First run: the browser engine isn't downloaded yet. Start the download and
    # tell the UI to show progress instead of failing the launch.
    if not engine.is_installed(eng):
        st = engine.ensure_async(eng)
        response.status_code = 202
        return {"engine_downloading": eng, "status": st}
    return manager.launch(prof.id, url=body.url, headless=body.headless)


@app.post("/api/profiles/{name_or_id}/stop")
def stop_profile(name_or_id: str):
    try:
        prof = store.get(name_or_id)
    except KeyError:
        raise HTTPException(404, "profile not found")
    return {"stopped": manager.stop(prof.id)}


class BatchReq(BaseModel):
    ids: list[str]
    url: str = "about:blank"
    headless: bool = False


@app.post("/api/batch/launch")
def batch_launch(body: BatchReq):
    out = []
    for name_or_id in body.ids:
        try:
            prof = store.get(name_or_id)
            out.append(manager.launch(prof.id, url=body.url, headless=body.headless))
        except Exception as e:  # noqa: BLE001
            out.append({"profile_id": name_or_id, "error": str(e)})
    return out


@app.post("/api/batch/stop")
def batch_stop(body: BatchReq):
    out = []
    for name_or_id in body.ids:
        try:
            prof = store.get(name_or_id)
            out.append({"profile_id": prof.id, "stopped": manager.stop(prof.id)})
        except Exception as e:  # noqa: BLE001
            out.append({"profile_id": name_or_id, "error": str(e)})
    return out


@app.get("/api/running")
def running():
    return manager.status()


@app.post("/api/stop-all")
def stop_all():
    return {"stopped": manager.stop_all()}


# ---------- auto-name & groups ----------

@app.get("/api/next-name")
def next_name():
    return {"name": store.next_profile_name()}


@app.get("/api/groups")
def groups():
    return store.list_groups()


@app.post("/api/groups", status_code=201)
def add_group(body: GroupIn):
    store.add_group(body.name.strip())
    return store.list_groups()


@app.delete("/api/groups/{name}", status_code=204)
def delete_group(name: str):
    try:
        store.delete_group(name)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------- proxy pool ----------

@app.get("/api/proxies")
def list_proxies(group: Optional[str] = None):
    return store.list_proxies(group=group)


@app.get("/api/proxy-groups")
def proxy_groups():
    return store.proxy_groups()


@app.post("/api/proxies", status_code=201)
def add_proxy(body: ProxyIn):
    try:
        return store.add_proxy(body.raw, label=body.label, note=body.note, group=body.group)
    except Exception as e:
        raise HTTPException(400, str(e))


class BulkProxies(BaseModel):
    text: str


@app.post("/api/proxies/bulk")
def add_proxies_bulk(body: BulkProxies):
    return store.add_proxies_bulk(body.text)


@app.patch("/api/proxies/{pid}")
def patch_proxy(pid: str, body: ProxyPatch):
    try:
        return store.update_proxy(
            pid,
            raw=body.raw if body.raw is not None else ...,
            label=body.label if body.label is not None else ...,
            note=body.note if body.note is not None else ...,
            group=body.group if body.group is not None else ...,
        )
    except KeyError:
        raise HTTPException(404, "proxy not found")
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/proxies/{pid}", status_code=204)
def delete_proxy(pid: str):
    try:
        store.delete_proxy(pid)
    except KeyError:
        raise HTTPException(404, "proxy not found")


@app.post("/api/proxies/{pid}/enabled")
def set_proxy_enabled(pid: str, enabled: bool = True):
    try:
        return store.set_proxy_enabled(pid, enabled)
    except KeyError:
        raise HTTPException(404, "proxy not found")


@app.post("/api/proxies/check-all")
def check_all_proxies():
    return store.check_all_proxies()


# ---------- proxy providers (dynamic) ----------

class ProviderIn(BaseModel):
    kind: str          # api_extract | rotating_gateway
    url: str
    label: Optional[str] = None
    note: str = ""


@app.get("/api/providers")
def list_providers():
    return store.list_providers()


@app.post("/api/providers", status_code=201)
def add_provider(body: ProviderIn):
    try:
        return store.add_provider(body.kind, body.url, label=body.label, note=body.note)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/providers/{pid}", status_code=204)
def delete_provider(pid: str):
    try:
        store.delete_provider(pid)
    except KeyError:
        raise HTTPException(404, "provider not found")


@app.post("/api/providers/{pid}/refresh")
def refresh_provider(pid: str):
    try:
        return store.refresh_provider(pid)
    except KeyError:
        raise HTTPException(404, "provider not found")
    except Exception as e:
        raise HTTPException(400, f"refresh failed: {e}")


@app.post("/api/proxies/{pid}/check")
def check_pool_proxy(pid: str):
    try:
        p = store.get_proxy(pid)
    except KeyError:
        raise HTTPException(404, "proxy not found")
    try:
        geo = check_and_locate(Proxy.parse(p["raw"]))
        return store.record_proxy_check(pid, geo)
    except Exception as e:
        store.record_proxy_check(pid, None)
        raise HTTPException(400, f"proxy check failed: {e}")


# ---------- ad-hoc proxy check (not in pool) ----------

@app.get("/api/proxy/parse")
def proxy_parse(raw: str):
    """Auto-detect a pasted proxy's format (no network). Returns the normalized
    pieces so the UI can confirm what it understood."""
    try:
        p = Proxy.parse(raw)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": True, "scheme": p.scheme, "host": p.host, "port": p.port,
        "has_auth": bool(p.username), "normalized": p.full_url(),
    }


@app.get("/api/proxy/check")
def proxy_check(proxy: str):
    try:
        p = Proxy.parse(proxy)
        geo = check_and_locate(p)
    except Exception as e:
        raise HTTPException(400, f"proxy check failed: {e}")
    return geo.__dict__


# ---------- import / export ----------

@app.get("/api/export")
def export_all():
    return store.export_all()


@app.post("/api/import")
def import_profiles(profiles: list[dict]):
    out = []
    for d in profiles:
        try:
            out.append(_view(store.import_profile(d)))
        except Exception as e:
            out.append({"error": str(e), "name": d.get("name")})
    return out
