"""Getting a local model in place without a terminal: is Ollama installed and running, which models it has, which one
suits this computer, installing the official app, and pulling a model with progress the page can show. Ported from
Trailmix. On a Mac and on Windows it installs the official app, checked against Ollama's own signature. On Linux Ollama's
install script needs root, so the app never runs it: it shows the command, and watches for Ollama answering.

Lockdown refuses an install or a download ("Turn off Lockdown to download it"): both reach the internet."""
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

from . import ai, computer, hardware, lockdown, model_catalog, resources, settings

log = logging.getLogger("core.ollama")

# Which models to offer is the model catalog's call (model_catalog.py), so a newer release is a table change, not a code
# change. 16 GB Macs and up get the big one; smaller ones the small one. (The Lodge's own measurements, 2026-10-23, of
# the 7B and 3B then on offer: neither reads a long note as well as a cloud model; the 7B could do the lighter jobs.)
RECOMMENDED_BIG = model_catalog.recommended("big")
RECOMMENDED_SMALL = model_catalog.recommended("small")
BIG_FROM_GB = 15
BIG_FROM_CARD_GB = 8      # a graphics card's own memory: the big model takes about 6.6 GB of it

# The official Mac app, signed and notarized by Ollama (Infra Technologies, Inc). Only a download that carries that
# signature is installed.
OLLAMA_ZIP = "https://ollama.com/download/Ollama-darwin.zip"
OLLAMA_TEAM = "3MU9H2V9Y9"
INSTALL_DIRS = [Path("/Applications"), Path.home() / "Applications"]   # the first one that's writable wins

# The official Windows installer, signed by Ollama (Authenticode); it installs for the current user into
# %LOCALAPPDATA%\Programs\Ollama. Only a download whose signature is valid and Ollama's is run.
OLLAMA_SETUP_EXE = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_WINDOWS_SIGNER = "ollama"  # must be in the signer certificate's subject

LINUX_INSTALL_COMMAND = "curl -fsSL https://ollama.com/install.sh | sh"
LINUX_INSTALL_PAGE = "https://ollama.com/download/linux"
LINUX_SERVICE_FILES = [Path("/etc/systemd/system/ollama.service"), Path("/usr/lib/systemd/system/ollama.service"),
                       Path("/lib/systemd/system/ollama.service")]
LINUX_BINARIES = [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]

_lock = threading.Lock()
_pull: dict = {}
_install: dict = {}


def _windows_app_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"


def app_path() -> Path | None:
    """The Ollama app: Ollama.app on a Mac, "ollama app.exe" (the tray app that runs the server) on Windows, the ollama
    command on Linux."""
    if sys.platform.startswith("linux"):
        found = shutil.which("ollama")
        if found:
            return Path(found)
        return next((p for p in LINUX_BINARIES if p.exists()), None)
    if sys.platform == "win32":
        for name in ("ollama app.exe", "ollama.exe"):
            if (_windows_app_dir() / name).exists():
                return _windows_app_dir() / name
        found = shutil.which("ollama")
        return Path(found) if found else None
    for folder in INSTALL_DIRS:
        if (folder / "Ollama.app").exists():
            return folder / "Ollama.app"
    return None


def recommended() -> str:
    """The model that suits this computer: by a Mac's memory, or a graphics card's own. On the CPU, where a model is only
    here because you chose it, the small one."""
    hw = hardware.profile()
    if hw["ai_runs_on"] == "gpu":
        return RECOMMENDED_BIG if hw["ai_memory_gb"] >= BIG_FROM_CARD_GB else RECOMMENDED_SMALL
    if hw["ai_runs_on"] == "cpu":
        return RECOMMENDED_SMALL
    return RECOMMENDED_BIG if resources.snapshot()["ram_total_gb"] >= BIG_FROM_GB else RECOMMENDED_SMALL


def suggestion(cfg: dict, tags: list[dict]) -> dict | None:
    """A newer model to offer someone who already has one: {"model": what to get, "replaces": what they use now}, or None.
    Only for a model the catalog lists whose family a better one has replaced. Never when they've chosen a model
    themselves, or brought one the catalog doesn't know, or already said "not now" to this suggestion, or when they
    have the model already."""
    if cfg.get("ollama_model"):
        return None
    using = ai.preferred_ollama_model(tags)
    wanted = recommended()
    if not using or model_catalog.family_of(using) is None or cfg.get("model_suggestion_dismissed") == wanted:
        return None
    if any(m["name"] in (wanted, f"{wanted}:latest") for m in tags):
        return None
    if model_catalog.rank(wanted) >= model_catalog.rank(using):
        return None
    return {"model": wanted, "replaces": using}


def dismiss_suggestion(model: str) -> None:
    """"Not now": don't offer this model again. A later catalog that recommends a different one offers that."""
    settings.update({"ai.model_suggestion_dismissed": model})


def _linux_commands(installed: bool) -> dict:
    """On Linux, what to run yourself (the app runs nothing as root): the install command and Ollama's page for it, or,
    once installed, how to start it. None elsewhere."""
    if not sys.platform.startswith("linux"):
        return {"install_command": None, "install_page": None, "start_command": None}
    service = any(p.exists() for p in LINUX_SERVICE_FILES)
    return {
        "install_command": None if installed else LINUX_INSTALL_COMMAND,
        "install_page": LINUX_INSTALL_PAGE,
        "start_command": ("sudo systemctl start ollama" if service else "ollama serve") if installed else None,
    }


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
    installed = app_path() is not None
    return {
        "can_install": sys.platform in ("darwin", "win32"),
        "installed": installed,
        **_linux_commands(installed),
        "install": install or None,
        "reachable": bool(tags) or _reachable(cfg["ollama_url"]),
        "models": [m["name"] for m in tags],
        "using": ai.model_for("ollama", cfg) if tags else "",
        "recommended": recommended(),
        "suggestion": suggestion(cfg, tags) if tags else None,
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


# ── Ollama itself (a Mac, and Windows) ─────────────────────────────────

def start_install() -> bool:
    """Downloads, checks and installs Ollama, then opens it. Opens it if it's installed but not running."""
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
            app = _download_and_install_windows() if sys.platform == "win32" else _download_and_install()
        _set(status="Starting Ollama", progress=None)
        _open(app)
        for _ in range(60):
            if _reachable(url):
                _set(active=False, status="ready", progress=1.0)
                return
            time.sleep(1)
        raise RuntimeError(f"Ollama was installed but didn't start. Open it from {computer.word('apps')}.")
    except Exception as e:  # noqa: BLE001 - shown on the card
        log.warning("Installing Ollama failed: %s", e)
        _set(active=False, error=str(e)[:300])


def _open(app: Path) -> None:
    """Starts the Ollama app without bringing it to the front."""
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([str(app)], creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(["/usr/bin/open", "-g", str(app)], check=True, timeout=20)   # -g: don't steal focus


def _download(url: str, target: Path) -> None:
    _set(status="Downloading Ollama")
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(60, read=120)) as r:
        if r.status_code >= 400:
            raise RuntimeError(f"Couldn't download Ollama (HTTP {r.status_code})")
        total = int(r.headers.get("content-length") or 0)
        got = 0
        with open(target, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if total:
                    _set(progress=min(0.99, got / total))


def _download_and_install() -> Path:
    work = Path(tempfile.mkdtemp(prefix="family-ollama-"))
    try:
        archive = work / "Ollama-darwin.zip"
        _download(OLLAMA_ZIP, archive)
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


def _download_and_install_windows() -> Path:
    work = Path(tempfile.mkdtemp(prefix="family-ollama-"))
    try:
        setup = work / "OllamaSetup.exe"
        _download(OLLAMA_SETUP_EXE, setup)
        _set(status="Checking Ollama's signature", progress=None)
        _verify_windows(setup)
        _set(status="Installing Ollama")
        subprocess.run([str(setup), "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"], check=True, timeout=900)
        app = app_path()
        if app is None:
            raise RuntimeError("Ollama's installer finished, but Ollama isn't where it should be")
        return app
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _powershell() -> str:
    """Windows' own PowerShell, by its full path: the server's PATH is only the app's helpers and the system's top
    folders (desktop/src-tauri/src/server.rs), and PowerShell lives further down. Nor could another program on a PATH
    then stand in for the check of a download's signature."""
    return str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def _verify_windows(setup: Path) -> None:
    """Refuses a download whose Authenticode signature isn't valid, or isn't Ollama's."""
    path = str(setup).replace("'", "''")
    script = (f"$s = Get-AuthenticodeSignature -LiteralPath '{path}'; $s.Status.ToString(); "
              "if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { '' }")
    # Windows' own PowerShell looks for its modules in PSModulePath. An app started from PowerShell 7 inherits PowerShell
    # 7's value, whose copy of the Security module Windows PowerShell can't load: the check then prints nothing at all,
    # which read as a bad signature on a good download. Without the variable it uses its own folders.
    env = {name: value for name, value in os.environ.items() if name.upper() != "PSMODULEPATH"}
    done = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=120, env=env)
    lines = [line.strip() for line in done.stdout.splitlines() if line.strip()]
    status, subject = lines[0] if lines else "", lines[1] if len(lines) > 1 else ""
    problem = signature_problem(status, subject)
    if problem:
        log.warning("Ollama's signature: status %r, signer %r, exit %s, PowerShell said: %s",
                    status, subject, done.returncode, (done.stderr or "").strip()[:500])
        raise RuntimeError(problem)


def signature_problem(status: str, subject: str) -> str | None:
    """Why a Windows download of Ollama isn't trusted (its signature's status and signer, as PowerShell's
    Get-AuthenticodeSignature reports them), or None when it is."""
    if status.strip().lower() != "valid":
        return "The Ollama download failed its signature check, so it wasn't installed"
    if OLLAMA_WINDOWS_SIGNER not in subject.lower():
        return "The Ollama download isn't signed by Ollama, so it wasn't installed"
    return None
