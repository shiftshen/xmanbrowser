"""XMan CLI — profile management, proxy binding, launch, and the local API service.

Examples:
    xman create work --os macos --proxy socks5://user:pass@host:1080
    xman list
    xman show work
    xman check-proxy socks5://user:pass@host:1080
    xman launch work --url https://browserleaks.com/webgl
    xman serve                      # start the local control API (for the UI)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import fingerprint as fp
from . import store, manager
from .proxy import Proxy, check_and_locate

app = typer.Typer(add_completion=False, help="XMan — open-source macOS fingerprint browser")
console = Console()


@app.callback()
def _init():
    store.init(migrate=True)


@app.command()
def create(
    name: str,
    os: str = typer.Option("macos", help="macos | windows | linux"),
    engine: str = typer.Option("camoufox", help="camoufox (Firefox) | chromium (real Chrome)"),
    proxy: Optional[str] = typer.Option(None, help="scheme://user:pass@host:port"),
    group: str = typer.Option("default"),
    note: str = typer.Option(""),
    seed: Optional[int] = typer.Option(None, help="reproducible fingerprint seed"),
):
    """Create a profile with a fresh, internally-consistent fingerprint."""
    prof = store.create(name, os_name=os, engine=engine, proxy_raw=proxy, group=group, note=note, seed=seed)
    console.print(f"[green]created[/] [bold]{prof.name}[/] (id={prof.id})")
    _print_summary(prof)


@app.command(name="list")
def list_cmd(group: Optional[str] = None, search: Optional[str] = None):
    """List profiles."""
    profs = store.all_profiles(group=group, search=search)
    if not profs:
        console.print("[yellow]no profiles[/] — run: xman create <name>")
        raise typer.Exit()
    t = Table("id", "name", "group", "os", "screen", "proxy", "running", "note")
    running = {r["profile_id"] for r in manager.status()}
    for p in profs:
        s = fp.summary(p.fingerprint)
        t.add_row(p.id, p.name, p.group, s["os"], s["screen"], p.proxy_raw or "-",
                  "●" if p.id in running else "", p.note)
    console.print(t)


@app.command()
def show(name: str):
    """Show a profile's fingerprint highlights."""
    prof = _load(name)
    _print_summary(prof)
    console.print(f"user-data-dir: {prof.user_data_dir}")


@app.command()
def edit(
    name: str,
    proxy: Optional[str] = typer.Option(None),
    group: Optional[str] = typer.Option(None),
    note: Optional[str] = typer.Option(None),
    rename: Optional[str] = typer.Option(None),
):
    """Update a profile's proxy / group / note / name."""
    prof = store.update(
        name,
        proxy_raw=proxy if proxy is not None else ...,
        group=group if group is not None else ...,
        note=note if note is not None else ...,
        name=rename if rename is not None else ...,
    )
    console.print(f"[green]updated[/] {prof.name}")
    _print_summary(prof)


@app.command()
def clone(name: str, new_name: str, keep_fingerprint: bool = typer.Option(False)):
    """Clone a profile (new fingerprint by default)."""
    prof = store.clone(name, new_name, regenerate_fingerprint=not keep_fingerprint)
    console.print(f"[green]cloned[/] -> {prof.name} (id={prof.id})")


@app.command()
def delete(name: str, keep_data: bool = typer.Option(False, help="keep the user-data-dir")):
    """Delete a profile (and stop it if running)."""
    try:
        manager.stop(store.get(name).id)
    except Exception:
        pass
    store.delete(name, wipe_userdata=not keep_data)
    console.print(f"[red]deleted[/] {name}")


@app.command(name="check-proxy")
def check_proxy(proxy: str):
    """Verify a proxy works and print its exit IP + geo."""
    p = Proxy.parse(proxy)
    console.print(f"checking {p.server_url()} ...")
    geo = check_and_locate(p)
    console.print(
        f"[green]ok[/] exit IP [bold]{geo.ip}[/] — {geo.city}, {geo.country} "
        f"({geo.country_code}) tz={geo.timezone}"
    )


@app.command()
def launch(
    name: str,
    url: str = typer.Option("https://browserleaks.com/webgl"),
    headless: bool = typer.Option(False),
    background: bool = typer.Option(False, "--bg", help="launch as a managed background process"),
    no_proxy_check: bool = typer.Option(False),
):
    """Launch Camoufox for a profile (fingerprint + proxy + geoip)."""
    prof = _load(name)
    if prof.proxy and not no_proxy_check:
        geo = check_and_locate(prof.proxy)
        console.print(f"proxy ok — exit {geo.ip} {geo.country_code} tz={geo.timezone}")

    if background:
        res = manager.launch(prof.id, url=url, headless=headless)
        console.print(f"[green]launched[/] {prof.name} pid={res['pid']}"
                      + (" (already running)" if res.get("already_running") else ""))
        return

    from .launcher import launch as do_launch
    console.print(f"launching [bold]{prof.name}[/] ...")
    with do_launch(prof, headless=headless) as ctx:
        page = ctx.new_page()
        page.goto(url)
        console.print(f"[green]open[/] — {url}\nclose the window (or Ctrl-C) to exit.")
        try:
            while ctx.pages:
                page.wait_for_timeout(500)
        except KeyboardInterrupt:
            pass


@app.command()
def stop(name: str):
    """Stop a running background instance."""
    ok = manager.stop(_load(name).id)
    console.print("[green]stopped[/]" if ok else "[yellow]not running[/]")


@app.command()
def running():
    """List running background instances."""
    rows = manager.status()
    if not rows:
        console.print("[yellow]none running[/]")
        raise typer.Exit()
    t = Table("profile_id", "pid")
    for r in rows:
        t.add_row(r["profile_id"], str(r["pid"]))
    console.print(t)


@app.command(name="export")
def export_cmd(out: Path = typer.Option(Path("xman-profiles.json"))):
    """Export all profiles to JSON."""
    out.write_text(json.dumps(store.export_all(), indent=2, ensure_ascii=False))
    console.print(f"[green]exported[/] {len(store.all_profiles())} -> {out}")


@app.command(name="import")
def import_cmd(path: Path):
    """Import profiles from a JSON file."""
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        data = [data]
    n = 0
    for d in data:
        try:
            store.import_profile(d)
            n += 1
        except Exception as e:
            console.print(f"[red]skip[/] {d.get('name')}: {e}")
    console.print(f"[green]imported[/] {n}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8723):
    """Start the local control API (for the UI)."""
    import uvicorn
    console.print(f"XMan API on http://{host}:{port}  (docs at /docs)")
    uvicorn.run("xman.service:app", host=host, port=port, log_level="info")


def _load(name: str):
    try:
        return store.get(name)
    except KeyError:
        console.print(f"[red]profile not found:[/] {name}")
        raise typer.Exit(1)


def _print_summary(prof):
    s = fp.summary(prof.fingerprint)
    t = Table("field", "value", show_header=False)
    for k, v in s.items():
        t.add_row(k, str(v))
    if prof.proxy_raw:
        t.add_row("proxy", prof.proxy_raw)
    console.print(t)


if __name__ == "__main__":
    app()
