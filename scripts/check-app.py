#!/usr/bin/env python
"""Behaviour checks for the built Mac app. Run after scripts/build-app.sh:

    .venv/bin/python scripts/check-app.py

It makes a copy of dist-app/<Name>.app on a spare port with its own data folder (so your real app and data are
untouched; quit the app first if it's open, so no stray window answers) and checks that:
  - the server starts, with the app as its parent, and the data folder is private;
  - a server killed from outside is started again, and after three crashes in two minutes the app stops trying;
  - quitting the app leaves no server behind, and neither does force-killing the app;
  - a second copy of the app uses the first one's server instead of fighting it for the port, and doesn't stop it;
  - when the first copy quits (taking its server with it), the second starts its own instead of being left without.
"""
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JSON = json.loads((ROOT / "app.json").read_text())
PORT = 8795
FAILED: list[str] = []


def ok(condition: bool, text: str) -> None:
    print(("  OK   " if condition else "  FAIL ") + text)
    if not condition:
        FAILED.append(text)


def answering() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/app", timeout=2) as r:
            return json.load(r).get("id") == APP_JSON["id"]
    except Exception:  # noqa: BLE001
        return False


def wait(condition, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.25)
    return condition()


def sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True).stdout.strip()


def server_pids() -> list[int]:
    return [int(p) for p in sh("lsof", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN", "-t").split()]


def app_pids(app: Path) -> list[int]:
    return [int(p) for p in sh("pgrep", "-f", str(app / "Contents/MacOS")).split()]


def launch(app: Path, data: Path) -> None:
    subprocess.run(["open", "-n", "--env", f"{APP_JSON['envPrefix']}_NO_OPEN=1", "--env", f"{APP_JSON['envPrefix']}_DATA_DIR={data}", str(app)], check=True)


def quit_app(app: Path) -> None:
    subprocess.run(["osascript", "-e", f'tell application "{app}" to quit'], capture_output=True)


def main() -> int:
    built = ROOT / "dist-app" / f"{APP_JSON['name']}.app"
    if not built.exists():
        print("Build the app first: scripts/build-app.sh")
        return 2
    if server_pids():
        print(f"Something is already listening on port {PORT}; stop it first.")
        return 2
    work = Path(tempfile.mkdtemp(prefix=f"{APP_JSON['id']}-app-check-"))
    app, data = work / built.name, work / "data"
    subprocess.run(["ditto", str(built), str(app)], check=True)
    subprocess.run(["plutil", "-replace", "FamilyPort", "-string", str(PORT), str(app / "Contents/Info.plist")], check=True)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True, capture_output=True)

    try:
        print("Starting")
        launch(app, data)
        ok(wait(answering, 40), "the server starts and answers")
        pids = server_pids()
        app_pid = int(sh("pgrep", "-n", "-f", str(app / "Contents/MacOS")))
        ok(len(pids) == 1 and int(sh("ps", "-o", "ppid=", "-p", str(pids[0]))) == app_pid, "it is the app's own child")
        ok(stat.S_IMODE(data.stat().st_mode) == 0o700, "the data folder is readable only by you")

        print("A server that dies")
        for crash in (1, 2):
            old = server_pids()[0]
            os.kill(old, signal.SIGKILL)
            back = wait(lambda: answering() and server_pids() and server_pids()[0] != old, 20)
            ok(back, f"crash {crash} of 3: the server is started again")
        os.kill(server_pids()[0], signal.SIGKILL)
        time.sleep(6)
        ok(not answering() and not server_pids(), "crash 3 within two minutes: it stops trying (the menu explains why)")
        quit_app(app)
        ok(wait(lambda: not app_pids(app), 10), "the app quits")

        print("Quitting")
        launch(app, data)
        wait(answering, 40)
        quit_app(app)
        ok(wait(lambda: not app_pids(app) and not server_pids(), 15), "quitting leaves no server running")
        launch(app, data)
        wait(answering, 40)
        for pid in app_pids(app):
            os.kill(pid, signal.SIGKILL)
        ok(wait(lambda: not server_pids(), 15), "even force-killing the app doesn't leave the server running")

        print("Two copies")
        launch(app, data)
        wait(answering, 40)
        first = server_pids()
        launch(app, data)
        time.sleep(6)
        ok(server_pids() == first and answering(), "a second copy shares the first one's server (no fight over the port)")
        ok(len(app_pids(app)) >= 2, "both copies are running")
        newest = max(app_pids(app))
        os.kill(newest, signal.SIGTERM)
        time.sleep(4)
        ok(answering() and server_pids() == first, "closing the second copy doesn't stop the first one's server")
        launch(app, data)
        time.sleep(6)
        oldest, newest = min(app_pids(app)), max(app_pids(app))
        os.kill(oldest, signal.SIGTERM)
        owner = lambda: int(sh("ps", "-o", "ppid=", "-p", str(server_pids()[0]))) if server_pids() else None
        ok(wait(lambda: answering() and owner() == newest, 30), "when the first copy quits, the second starts its own server")
    finally:
        for pid in app_pids(app):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for pid in server_pids():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        shutil.rmtree(work, ignore_errors=True)
    print("\nAll good." if not FAILED else f"\n{len(FAILED)} problem(s).")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
