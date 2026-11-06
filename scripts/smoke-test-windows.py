#!/usr/bin/env python3
"""The release gate on Windows (scripts/smoke-test.sh is the Mac's): installs the built installer silently into a
temporary folder, checks the installed app as it really is, and uninstalls it. Your own data is never touched: the
app runs with a throwaway data folder and on a port of its own.

  python scripts/smoke-test-windows.py dist-app/TheLodge-0.8.0-windows-x64.exe
  python scripts/smoke-test-windows.py dist-app/TheLodge-0.8.0-windows-x64.exe previous/TheLodge-0.7.1-windows-x64.exe
  python scripts/smoke-test-windows.py --ollama dist-app/TheLodge-0.8.0-windows-x64.exe

What it checks, in order:
  1. the installer installs, silently, and the files the app needs are there, built for this arch
  2. --version says the installer's version, and --about the real install's paths (the bundled server is found, the
     data goes in %LOCALAPPDATA%), not a development build's
  3. the app starts its server, which answers as this app and says it's on Windows in the desktop shell, and serves
     the web app; the hardware readout works, and without a usable graphics card it recommends a cloud AI (GitHub's
     runners have none); a second launch hands over to the first instead of starting another
  4. ending the app (as Task Manager would) takes its server with it
  5. the real window, pointed at the installed server, shows the web app (the page names itself): a picture of it is
     kept beside the installer
  6. the uninstaller removes the app

With a previous version's installer it then tries the update path, as someone on that version would meet it:
  7. the previous version installed, a mark left in its data, and its own updater pointed at a stand-in for GitHub's
     releases that has the new version: it downloads it, checks it, quits, installs it over itself and opens it
  8. Go back, from the new version's own updater: the previous version is back, the new one is skipped, and the mark
     is still there each time
--ollama instead installs the app and has it install Ollama, as Settings does: Ollama's real installer, its real signature
check, then Ollama answering. It really installs Ollama for this user, so it's for build machines.

Quit the app before running this on your own PC: going back ends whatever runs from the test's install folder only,
but the update test takes the app's port while it runs.
"""
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
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
FEED_PORT = PORT + 1
MARK = "Smoke Test"
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
    except Exception:  # noqa: BLE001 - a server still starting can fail any way; the caller just asks again
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


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"{URL}{path}", timeout=30) as r:
        return json.loads(r.read())


def check_advice() -> None:
    """The real hardware readout on this real machine, and the family's rule: no usable card, no local recommendation."""
    advice = get_json("/api/system")["advice"]
    print(f"advice: {advice['verdict']}; chip {advice['chip']!r}; card {advice['gpu']!r}; NPU {advice['npu']!r}; {advice['ram_gb']} GB")
    print(f"  {advice['notes'][0]}")
    if not advice["chip"]:
        raise Failure("the hardware readout couldn't read the processor's name")
    if not advice["gpu"] and advice["verdict"] != "cloud":
        raise Failure(f"no usable graphics card, but the advice is {advice['verdict']!r}, not 'cloud'")
    if not get_json("/api/ollama").get("can_install"):
        raise Failure("Ollama setup says it can't install on Windows")


def ollama_test(installer: Path, work: Path) -> None:
    """Has the installed app install Ollama, as Settings → AI does."""
    install, data = work / "o-app", work / "o-data"
    exe = install / f"{SLUG}.exe"
    log(f"Installing {installer.name}, then Ollama from inside it")
    subprocess.run([str(installer), "/S", f"/D={install}"], check=True, timeout=900)
    env = {**os.environ, f"{PREFIX}_DATA_DIR": str(data), f"{PREFIX}_PORT": str(PORT), f"{PREFIX}_NO_OPEN": "1", "TRAILMIX_FAMILY_DIR": "off"}
    subprocess.Popen([str(exe)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for_app(120)
        before = get_json("/api/ollama")
        print(f"before: installed {before['installed']}, running {before['reachable']}, would get {before['recommended']}")
        request = urllib.request.Request(f"{URL}/api/ollama/install", data=b"", method="POST")
        urllib.request.urlopen(request, timeout=30).read()
        deadline, last = time.time() + 1200, ""
        while time.time() < deadline:
            now = get_json("/api/ollama")
            install_state = now.get("install") or {}
            if install_state.get("status") != last:
                last = install_state.get("status")
                print(f"  {last}", flush=True)
            if install_state.get("error"):
                ollama_logs()
                raise Failure(f"installing Ollama failed: {install_state['error']}")
            if now["installed"] and now["reachable"] and not install_state.get("active"):
                print(f"after: installed, running, models {now['models']}")
                return
            time.sleep(3)
        raise Failure("Ollama wasn't installed and answering after 20 minutes")
    finally:
        end_install(install)


def ollama_logs() -> None:
    """What Ollama itself said, when it didn't start: its tray app's and server's logs, and what's running."""
    folder = Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama"
    for name in ("app.log", "server.log"):
        path = folder / name
        print(f"-- {path} --")
        print(path.read_text(errors="replace")[-3000:] if path.exists() else "(not there)")
    running = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Process *ollama* | Format-Table Id, Path -AutoSize | Out-String"],
                             capture_output=True, text=True)
    print(f"-- running --\n{running.stdout or '(nothing)'}", flush=True)


def end_install(install: Path) -> None:
    """Ends every program running from the install (the app, its server, an updater it started). Matched on the
    test's own folder names: Windows reports a program's path in the form it was started with, which on GitHub's
    runners is the short one (C:\\Users\\RUNNER~1\\...) as often as the long one."""
    tail = f"\\{install.parent.name}\\{install.name}\\".replace("'", "''")
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Get-Process | Where-Object {{ $_.Path -and $_.Path.ToLower().Contains('{tail.lower()}') }} | Stop-Process -Force"],
                   capture_output=True)
    if not wait_gone(20):
        raise Failure(f"couldn't end the app running from {install}")


def wait_for_version(version: str, seconds: float) -> dict:
    deadline = time.time() + seconds
    info = None
    while time.time() < deadline:
        info = app_info()
        if info and info.get("id") == IDENTITY["id"] and info.get("version") == version:
            return info
        time.sleep(1)
    raise Failure(f"{NAME} {version} didn't come up at {URL} (last answer: {info and info.get('version')})")


def your_name() -> str | None:
    with urllib.request.urlopen(f"{URL}/api/settings", timeout=5) as r:
        return json.loads(r.read())["values"].get("core.your_name")


def set_your_name(value: str) -> None:
    request = urllib.request.Request(f"{URL}/api/settings", data=json.dumps({"core.your_name": value}).encode(),
                                     headers={"Content-Type": "application/json"}, method="PUT")
    urllib.request.urlopen(request, timeout=10).read()


def serve_feed(folder: Path) -> http.server.ThreadingHTTPServer:
    """A stand-in for GitHub's releases: the list as JSON and the files, from `folder`."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))
    handler.log_message = lambda *args: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", FEED_PORT), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def publish(feed: Path, installer: Path, version: str, arch: str) -> dict:
    """Puts an installer in the stand-in feed as a release names it (build-windows.py), with its checksum."""
    import hashlib
    name = f"{SLUG}-{version}-windows-{arch}.exe"
    shutil.copy2(installer, feed / name)
    digest = hashlib.sha256((feed / name).read_bytes()).hexdigest()
    (feed / f"{name}.sha256").write_text(f"{digest}  {name}\n")
    base = f"http://127.0.0.1:{FEED_PORT}"
    return {"tag_name": f"v{version}", "prerelease": False, "draft": False, "html_url": f"{base}/",
            "assets": [{"name": n, "browser_download_url": f"{base}/{n}"} for n in (name, f"{name}.sha256")]}


def update_test(new: Path, new_version: str, old: Path, arch: str, work: Path) -> None:
    old_version = re.match(rf"{re.escape(SLUG)}-(.+)-windows-[a-z0-9]+\.exe$", old.name)
    old_version = old_version.group(1) if old_version else None
    install, data, feed = work / "u-app", work / "u-data", work / "feed"
    exe = install / f"{SLUG}.exe"
    feed.mkdir()
    log(f"7. Updating {old.name} to {new_version} with its own updater")
    subprocess.run([str(old), "/S", f"/D={install}"], check=True, timeout=900)
    old_version = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60).stdout.strip() or old_version
    if not old_version:
        raise Failure(f"couldn't tell which version {old.name} is")
    releases = [publish(feed, new, new_version, arch), publish(feed, old, old_version, arch)]
    (feed / "releases.json").write_text(json.dumps(releases))
    server = serve_feed(feed)
    base_env = {**os.environ, f"{PREFIX}_DATA_DIR": str(data), f"{PREFIX}_PORT": str(PORT), f"{PREFIX}_NO_OPEN": "1",
                f"{PREFIX}_UPDATE_URL": f"http://127.0.0.1:{FEED_PORT}/releases.json", f"{PREFIX}_UPDATE_DELAY": "15",  # (time to leave the mark first)
                "TRAILMIX_FAMILY_DIR": "off"}
    try:
        app = subprocess.Popen([str(exe)], env={**base_env, f"{PREFIX}_UPDATE_TEST": "install"},
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for_version(old_version, 120)
        set_your_name(MARK)
        print(f"{old_version} is up, with a mark in its data; its updater is looking")
        try:
            wait_for_version(new_version, 300)
        except Failure:
            print(f"-- update.log --\n{tail(data / 'logs' / 'update.log')}", file=sys.stderr)
            raise
        said = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
        saved = json.loads((data / "updates.json").read_text())
        print(f"updated: {said}; updates.json {saved}")
        if said != new_version:
            raise Failure(f"the installed program says {said}, not {new_version}")
        if saved.get("previous") != old_version:
            raise Failure(f"the update didn't remember {old_version} to go back to")
        if your_name() != MARK:
            raise Failure("the data didn't survive the update")
        app.wait(timeout=30)  # the old copy quit for the install

        log(f"8. Going back to {old_version} with the new version's own updater")
        end_install(install)
        subprocess.Popen([str(exe)], env={**base_env, f"{PREFIX}_UPDATE_TEST": "go-back"},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_for_version(old_version, 300)
        except Failure:
            print(f"-- update.log --\n{tail(data / 'logs' / 'update.log')}", file=sys.stderr)
            raise
        saved = json.loads((data / "updates.json").read_text())
        print(f"went back; updates.json {saved}")
        if saved.get("skipped") != new_version or saved.get("previous"):
            raise Failure(f"going back should skip {new_version} and forget what to go back to: {saved}")
        if your_name() != MARK:
            raise Failure("the data didn't survive going back")
    finally:
        end_install(install)
        server.shutdown()
    subprocess.run([str(install / "uninstall.exe"), "/S", f"_?={install}"], timeout=600)


def main(argv: list[str]) -> int:
    if sys.platform != "win32":
        print("The Windows smoke test runs on Windows.", file=sys.stderr)
        return 2
    with_ollama = "--ollama" in argv
    argv = [a for a in argv if a != "--ollama"]
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    installer = Path(argv[1]).resolve()
    previous = Path(argv[2]).resolve() if len(argv) == 3 else None
    if with_ollama:
        work = Path(tempfile.mkdtemp(prefix="smoke-"))
        try:
            ollama_test(installer, work)
            print(f"\nPASSED: Ollama, from inside {installer.name}")
            return 0
        except Failure as e:
            print(f"\nFAILED: {e}\n\n-- the server's log --\n{tail(work / 'o-data' / 'logs' / 'server.log')}", file=sys.stderr)
            return 1
        finally:
            shutil.rmtree(work, ignore_errors=True)
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
        # Everything that runs: Windows on ARM emulates x64, so an x64 part would pass every other check, only slowly.
        parts = [exe, install / "python" / "python.exe", *(install / "python").rglob("*.pyd"), *(install / "python").rglob("*.dll")]
        wrong = [str(p.relative_to(install)) for p in parts if pe_machine(p) != MACHINES[arch]]
        if wrong:
            raise Failure(f"not built for {arch}: {', '.join(wrong[:20])}")
        size = sum(p.stat().st_size for p in install.rglob("*") if p.is_file()) / 1e6
        print(f"installed: {size:.0f} MB; {len(parts)} compiled files, all built for {arch}")

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
        check_advice()
        server_log = data / "logs" / "server.log"
        if not server_log.is_file():
            raise Failure("the server log isn't in the data folder")

        second = subprocess.Popen([str(exe)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(second)
        try:
            second.wait(timeout=30)
        except subprocess.TimeoutExpired:
            raise Failure("a second launch kept running instead of handing over to the first") from None
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
        if previous:
            update_test(installer, version, previous, arch, work)
        print(f"\nPASSED: {installer.name}{f' (and the update from {previous.name})' if previous else ''}")
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
