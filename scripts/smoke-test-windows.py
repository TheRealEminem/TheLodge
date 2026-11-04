#!/usr/bin/env python3
"""The release gate on Windows (scripts/smoke-test.sh is the Mac's): installs the built installer silently into a
temporary folder, checks the installed app as it really is, and uninstalls it. Your own data is never touched: the
app runs with a throwaway data folder and on a port of its own.

  python scripts/smoke-test-windows.py dist-app/TheLodge-0.8.0-windows-x64.exe

What it checks, in order:
  1. the installer installs, silently, and the files the app needs are there, built for this arch
  2. --version says the installer's version, and --about the real install's paths (the bundled server is found, the
     data goes in %LOCALAPPDATA%), not a development build's
  3. the app starts its server, which answers as this app and says it's on Windows in the desktop shell, and serves
     the web app; a second launch hands over to the first instead of starting another
  4. ending the app (as Task Manager would) takes its server with it
  5. the real window, pointed at the installed server, shows the web app (the page names itself): a picture of it is
     kept beside the installer
  6. the uninstaller removes the app
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDENTITY = json.loads((ROOT / "app.json").read_text(encoding="utf-8"))
NAME = IDENTITY["name"]
SLUG = NAME.replace(" ", "")
PREFIX = IDENTITY["envPrefix"]
PORT = int(os.environ.get("SMOKE_PORT", "8796"))
URL = f"http://127.0.0.1:{PORT}"
MACHINES = {"x64": 0x8664, "arm64": 0xAA64}


class Failure(Exception):
    pass


def log(text: str) -> None:
    print(f"\n== {text}", flush=True)


def pe_machine(path: Path) -> int:
    with open(path, "rb") as f:
        head = f.read(4096)
    pe = int.from_bytes(head[0x3C:0x40], "little")
    return int.from_bytes(head[pe + 4:pe + 6], "little")


def app_info() -> dict | None:
    try:
        with urllib.request.urlopen(f"{URL}/api/app", timeout=2) as r:
            return json.loads(r.read()) if r.status == 200 else None
    except Exception:
        return None


def wait_for_app(seconds: float) -> dict:
    deadline = time.time() + seconds
    while time.time() < deadline:
        info = app_info()
        if info and info.get("id") == IDENTITY["id"]:
            return info
        time.sleep(1)
    raise Failure(f"{NAME}'s server didn't answer at {URL} within {seconds:.0f} s")


def wait_gone(seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if app_info() is None:
            return True
        time.sleep(0.5)
    return False


def tail(path: Path, lines: int = 60) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


def kill(proc: subprocess.Popen, tree: bool = True) -> None:
    if proc.poll() is None:
        subprocess.run(["taskkill", *(["/T"] if tree else []), "/F", "/PID", str(proc.pid)], capture_output=True)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pass


def server_env(install: Path, data: Path) -> dict:
    """The environment the app gives its server (desktop/src-tauri/src/server.rs), for starting it on its own."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    env.update({
        "PATH": f"{install / 'bin'};{root}\\System32;{root}",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1",
        f"{PREFIX}_DATA_DIR": str(data), f"{PREFIX}_UI_DIR": str(install / "ui"),
        f"{PREFIX}_SHELL": "desktop", f"{PREFIX}_SHELL_CAN": "quit,reveal,login", "TRAILMIX_FAMILY_DIR": "off",
    })
    return env


def main(argv: list[str]) -> int:
    if sys.platform != "win32":
        print("The Windows smoke test runs on Windows.", file=sys.stderr)
        return 2
    if len(argv) != 2:
        print(__doc__)
        return 2
    installer = Path(argv[1]).resolve()
    found = re.match(rf"{re.escape(SLUG)}-(.+)-windows-([a-z0-9]+)\.exe$", installer.name)
    if not found:
        print(f"{installer.name} isn't named {SLUG}-<version>-windows-<arch>.exe", file=sys.stderr)
        return 2
    version, arch = found.group(1), found.group(2)
    work = Path(tempfile.mkdtemp(prefix="smoke-"))
    install, data = work / "app", work / "data"
    exe = install / f"{SLUG}.exe"
    # (Windows' temporary folder is inside %LOCALAPPDATA%, so this copy would join your family apps: it doesn't.)
    env = {**os.environ, f"{PREFIX}_DATA_DIR": str(data), f"{PREFIX}_PORT": str(PORT), f"{PREFIX}_NO_OPEN": "1",
           "TRAILMIX_FAMILY_DIR": "off"}
    procs: list[subprocess.Popen] = []
    try:
        if app_info() is not None:
            raise Failure(f"something already answers at {URL}; set SMOKE_PORT to a free port")

        log(f"1. Installing {installer.name} into {install}")
        subprocess.run([str(installer), "/S", f"/D={install}"], check=True, timeout=900)
        for part in (exe, install / "python" / "python.exe", install / "app" / "app.json", install / "app" / "VERSION",
                     install / "app" / "core" / "server" / "app.py", install / "ui" / "index.html", install / "uninstall.exe"):
            if not part.exists():
                raise Failure(f"the install has no {part.relative_to(install)}")
        wrong = [p.name for p in (exe, install / "python" / "python.exe") if pe_machine(p) != MACHINES[arch]]
        if wrong:
            raise Failure(f"not built for {arch}: {', '.join(wrong)}")
        size = sum(p.stat().st_size for p in install.rglob("*") if p.is_file()) / 1e6
        print(f"installed: {size:.0f} MB, built for {arch}")

        log("2. --version and --about")
        said = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
        if said != version:
            raise Failure(f"--version says {said!r}, the installer is {version!r}")
        plain = {k: v for k, v in os.environ.items() if not k.startswith(f"{PREFIX}_")}
        about = json.loads(subprocess.run([str(exe), "--about"], capture_output=True, text=True, timeout=60, env=plain).stdout)
        print(json.dumps(about, indent=2))
        expected_data = Path(os.environ["LOCALAPPDATA"]) / NAME / "data"
        if not about.get("bundled"):
            raise Failure("the installed app doesn't find its bundled server (it would act like a development build)")
        if Path(about["data_dir"]) != expected_data:
            raise Failure(f"the data folder is {about['data_dir']}, not {expected_data}")
        if about.get("name") != NAME or about.get("version") != version:
            raise Failure(f"--about names {about.get('name')} {about.get('version')}")
        if (install / "app" / "VERSION").read_text().strip() != version:
            raise Failure("the bundled server's VERSION isn't the installer's")

        log("3. The app starts its server")
        app = subprocess.Popen([str(exe)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        procs.append(app)
        info = wait_for_app(120)
        computer = info.get("computer") or {}
        print(f"answering: {info['name']} {info['version']}, {computer}")
        if info.get("version") != version:
            raise Failure(f"the server says version {info.get('version')}, not {version}")
        if computer.get("os") != "windows" or computer.get("shell") != "desktop":
            raise Failure(f"the server thinks it's on {computer.get('os')} in {computer.get('shell')}")
        if not {"quit", "reveal", "login"} <= set(computer.get("can") or []):
            raise Failure(f"the shell says it can do only {computer.get('can')}")
        if computer.get("words", {}).get("here") != "this PC":
            raise Failure(f"the web app would say {computer.get('words', {}).get('here')!r}, not 'this PC'")
        with urllib.request.urlopen(f"{URL}/", timeout=10) as r:
            page = r.read().decode("utf-8", "replace")
        if "<div id=\"root\"" not in page and "id=root" not in page:
            raise Failure("the server doesn't serve the web app")
        server_log = data / "logs" / "server.log"
        if not server_log.is_file():
            raise Failure("the server log isn't in the data folder")

        second = subprocess.Popen([str(exe)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(second)
        try:
            second.wait(timeout=30)
        except subprocess.TimeoutExpired:
            raise Failure("a second launch kept running instead of handing over to the first")
        if app.poll() is not None or app_info() is None:
            raise Failure("a second launch stopped the first one")
        print("a second launch handed over to the first")

        log("4. Ending the app (not its server) takes the server with it")
        kill(app, tree=False)
        if not wait_gone(20):
            raise Failure("the server outlived the app")
        print("the server went with the app")

        log("5. The window")
        server = subprocess.Popen([str(install / "python" / "python.exe"), "-m", "uvicorn", "core.server.app:app",
                                   "--host", "127.0.0.1", "--port", str(PORT)],
                                  cwd=install / "app", env=server_env(install, data),
                                  stdout=open(work / "server.log", "ab"), stderr=subprocess.STDOUT)
        procs.append(server)
        wait_for_app(120)
        shot = installer.parent / f"{SLUG}-{version}-windows-{arch}-window.png"
        done = subprocess.run([str(exe), "--window-test", URL, str(shot), "60"], env=env, capture_output=True, text=True, timeout=180)
        print(done.stdout.strip())
        if done.returncode != 0:
            raise Failure(f"the window didn't show the web app (exit {done.returncode}): {done.stderr.strip()[-800:]}")
        kill(server)

        log("6. Uninstalling")
        subprocess.run([str(install / "uninstall.exe"), "/S", f"_?={install}"], check=True, timeout=600)
        if exe.exists():
            raise Failure("the uninstaller left the app behind")
        print("uninstalled")
        print(f"\nPASSED: {installer.name}")
        return 0
    except Failure as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        print(f"\n-- the server's log --\n{tail(data / 'logs' / 'server.log')}", file=sys.stderr)
        for proc in procs:
            if proc.stdout and proc.poll() is not None:
                print(f"\n-- the app's output --\n{proc.stdout.read()[-3000:]}", file=sys.stderr)
        return 1
    finally:
        for proc in procs:
            kill(proc)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
