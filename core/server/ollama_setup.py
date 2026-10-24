"""Getting a local model in place without a terminal: is Ollama installed and running, which models it has, which one
suits this Mac, installing the official app, and pulling a model with progress the page can show. Ported from Trailmix.

Lockdown refuses an install or a download ("Turn off Lockdown to download it"): both reach the internet."""
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

from . import ai, lockdown, resources, settings

log = logging.getLogger("core.ollama")

# Good at following instructions and structure. 16 GB Macs and up get the 7B; smaller ones the 3B. (The Lodge's own
# measurements, 2026-10-23: neither reads a long note as well as a cloud model; the 7B is the one that can do the lighter jobs.)
RECOMMENDED_BIG = "qwen2.5:7b"
RECOMMENDED_SMALL = "qwen2.5:3b"
BIG_FROM_GB = 15

# The official Mac app, signed and notarized by Ollama (Infra Technologies, Inc). Only a download that carries that
# signature is installed.
OLLAMA_ZIP = "https://ollama.com/download/Ollama-darwin.zip"
OLLAMA_TEAM = "3MU9H2V9Y9"
INSTALL_DIRS = [Path("/Applications"), Path.home() / "Applications"]   # the first one that's writable wins

_lock = threading.Lock()
_pull: dict = {}
_install: dict = {}


def app_path() -> Path | None:
    for folder in INSTALL_DIRS:
        if (folder / "Ollama.app").exists():
            return folder / "Ollama.app"
    return None


def recommended() -> str:
    total_gb = resources.snapshot()["ram_total_gb"]
    return RECOMMENDED_BIG if total_gb >= BIG_FROM_GB else RECOMMENDED_SMALL


def _reachable(url: str) -> bool:
    try:
        return httpx.get(f"{url}/api/version", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def status() -> dict:
    """Everything the setup card shows: installed, running, which models, what to get, and any work in progress."""
    cfg = settings.section("ai")
    tags = ai._ollama_tags(cfg)
    with _lock:
        pull, install = dict(_pull), dict(_install)
    return {
        "can_install": sys.platform == "darwin",
        "installed": app_path() is not None,
        "install": install or None,
        "reachable": bool(tags) or _reachable(cfg["ollama_url"]),
        "models": [m["name"] for m in tags],
        "using": ai.model_for("ollama", cfg) if tags else "",
        "recommended": recommended(),
        "pull": pull or None,
        "locked": lockdown.on(),
    }


# ── Models ─────────────────────────────────────────────────────────────

def start_pull(model: str) -> bool:
    """Starts downloading a model into Ollama in the background. False if a download is already running."""
    if (why := lockdown.blocked("Downloading a model")):
        raise PermissionError(why)
    url = settings.section("ai")["ollama_url"]
    with _lock:
        if _pull.get("active"):
            return False
        _pull.clear()
        _pull.update(model=model, active=True, progress=None, status="Starting", error=None)
    threading.Thread(target=_run_pull, args=(url, model), daemon=True, name="ollama-pull").start()
    return True


def _run_pull(url: str, model: str) -> None:
    try:
        with httpx.stream("POST", f"{url}/api/pull", json={"model": model, "stream": True},
                          timeout=httpx.Timeout(60, read=600)) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"Ollama answered {r.status_code}")
            for line in r.iter_lines():
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("error"):
                    raise RuntimeError(msg["error"])
                with _lock:
                    _pull["status"] = msg.get("status", "")
                    if msg.get("total"):
                        _pull["progress"] = min(1.0, msg.get("completed", 0) / msg["total"])
        with _lock:
            _pull.update(active=False, progress=1.0, status="success")
    except Exception as e:  # noqa: BLE001 - shown on the card
        log.warning("Pulling %s failed: %s", model, e)
        with _lock:
            _pull.update(active=False, error=f"Couldn't download {model}: {e}")


# ── Ollama itself (Mac) ────────────────────────────────────────────────

def start_install() -> bool:
    """Downloads, checks and installs Ollama.app, then opens it. Opens it if it's installed but not running."""
    if app_path() is None and (why := lockdown.blocked("Downloading Ollama")):
        raise PermissionError(why)
    url = settings.section("ai")["ollama_url"]
    with _lock:
        if _install.get("active"):
            return False
        _install.clear()
        _install.update(active=True, progress=None, status="Starting", error=None)
    threading.Thread(target=_run_install, args=(url,), daemon=True, name="ollama-install").start()
    return True


def _set(**fields) -> None:
    with _lock:
        _install.update(fields)


def _run_install(url: str) -> None:
    try:
        app = app_path()
        if app is None:
            app = _download_and_install()
        _set(status="Starting Ollama", progress=None)
        subprocess.run(["/usr/bin/open", "-g", str(app)], check=True, timeout=20)   # -g: don't steal focus
        for _ in range(60):
            if _reachable(url):
                _set(active=False, status="ready", progress=1.0)
                return
            time.sleep(1)
        raise RuntimeError("Ollama was installed but didn't start. Open it from Applications.")
    except Exception as e:  # noqa: BLE001 - shown on the card
        log.warning("Installing Ollama failed: %s", e)
        _set(active=False, error=str(e)[:300])


def _download_and_install() -> Path:
    work = Path(tempfile.mkdtemp(prefix="family-ollama-"))
    try:
        archive = work / "Ollama-darwin.zip"
        _set(status="Downloading Ollama")
        with httpx.stream("GET", OLLAMA_ZIP, follow_redirects=True, timeout=httpx.Timeout(60, read=120)) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"Couldn't download Ollama (HTTP {r.status_code})")
            total = int(r.headers.get("content-length") or 0)
            got = 0
            with open(archive, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        _set(progress=min(0.99, got / total))
        _set(status="Checking Ollama's signature", progress=None)
        subprocess.run(["/usr/bin/ditto", "-xk", str(archive), str(work / "x")], check=True, timeout=300)
        new = work / "x" / "Ollama.app"
        if not new.exists():
            raise RuntimeError("The Ollama download didn't contain Ollama.app")
        _verify(new)
        _set(status="Installing Ollama")
        for folder in INSTALL_DIRS:          # /Applications, or ~/Applications for someone who isn't an admin
            try:
                folder.mkdir(exist_ok=True)
                dest = folder / "Ollama.app"
                shutil.move(str(new), str(dest))
                return dest
            except PermissionError:
                continue
        raise RuntimeError("Couldn't put Ollama in Applications (no permission)")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _verify(app: Path) -> None:
    """Refuses anything not signed by Ollama's Apple developer team, or that Gatekeeper wouldn't accept."""
    check = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], capture_output=True, text=True)
    if check.returncode != 0:
        raise RuntimeError("The Ollama download failed its signature check, so it wasn't installed")
    info = subprocess.run(["/usr/bin/codesign", "-dv", "--verbose=2", str(app)], capture_output=True, text=True).stderr
    if f"TeamIdentifier={OLLAMA_TEAM}" not in info:
        raise RuntimeError("The Ollama download isn't signed by Ollama, so it wasn't installed")
    gate = subprocess.run(["/usr/sbin/spctl", "--assess", "--type", "execute", str(app)], capture_output=True, text=True)
    if gate.returncode != 0:
        raise RuntimeError("macOS didn't accept the Ollama download, so it wasn't installed")
