"""Local FastAPI control service (M2).

Exposes REST endpoints for the UI (M3) to manage profiles, proxies, and running
browser instances. Binds to 127.0.0.1 only — this is a local-first app, not a
network service.

Run:  xman serve         (or)   uvicorn xman.service:app
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import store, manager
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
    name: str
    os: str = "macos"
    proxy: Optional[str] = None
    group: str = "default"
    note: str = ""
    seed: Optional[int] = None


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
        prof = store.create(body.name, os_name=body.os, proxy_raw=body.proxy,
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

@app.post("/api/profiles/{name_or_id}/launch")
def launch_profile(name_or_id: str, body: LaunchReq):
    try:
        prof = store.get(name_or_id)
    except KeyError:
        raise HTTPException(404, "profile not found")
    return manager.launch(prof.id, url=body.url, headless=body.headless)


@app.post("/api/profiles/{name_or_id}/stop")
def stop_profile(name_or_id: str):
    try:
        prof = store.get(name_or_id)
    except KeyError:
        raise HTTPException(404, "profile not found")
    return {"stopped": manager.stop(prof.id)}


@app.get("/api/running")
def running():
    return manager.status()


@app.post("/api/stop-all")
def stop_all():
    return {"stopped": manager.stop_all()}


# ---------- proxy ----------

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
