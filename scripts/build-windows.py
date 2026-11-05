#!/usr/bin/env python3
"""Builds the Windows installer, dist-app/<Slug>-<version>-windows-<arch>.exe (and its .sha256): the Windows
counterpart of scripts/build-app.sh. It holds the desktop shell (desktop/, a Tauri app), the app's server (core/ and
its modules) with its own Python, and the web app, so nothing else needs installing.

  python scripts/build-windows.py                  the version in VERSION, for x64 PCs
  python scripts/build-windows.py --arch arm64     for ARM PCs, built on one (or set ARCH=arm64)
  set VERSION=0.8.0-build.7 ...                    another version (semver: X.Y.Z with an optional -suffix; the
                                                   installer won't take the Mac's 0.8.0.7 kind)
  python scripts/build-windows.py --stage-only     only stage build/windows (no Rust build, no installer)

Needs: Windows, Python 3.10+, Node.js, Rust (cargo) and internet access (the Python runtime is downloaded once into
build/cache, plus Python packages and Rust crates). A module that needs more than requirements.txt adds a
scripts/bundle-<module>.py, run with the staged Python (the Mac's scripts/bundle-<module>.sh can't run here).
The installer is unsigned for now (PORTING.md).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDENTITY = json.loads((ROOT / "app.json").read_text(encoding="utf-8"))
NAME = IDENTITY["name"]
SLUG = NAME.replace(" ", "")          # file names: GitHub turns spaces into dots
VERSION = os.environ.get("VERSION") or (ROOT / "VERSION").read_text().strip()
OUT = Path(os.environ.get("OUT") or ROOT / "dist-app")
CACHE = ROOT / "build" / "cache"
STAGE = ROOT / "build" / "windows"    # what goes beside the program (see desktop/src-tauri/src/server.rs)
DESKTOP = ROOT / "desktop"


def _arch() -> str:
    args = sys.argv[1:]
    arch = args[args.index("--arch") + 1] if "--arch" in args[:-1] else os.environ.get("ARCH") or "x64"
    if arch not in ("x64", "arm64"):
        print(f"x Unknown arch {arch!r}: x64 or arm64", file=sys.stderr)
        sys.exit(2)
    return arch


ARCH = _arch()
RUST_TARGET = {"x64": "x86_64-pc-windows-msvc", "arm64": "aarch64-pc-windows-msvc"}[ARCH]
MACHINE = {"x64": 0x8664, "arm64": 0xAA64}[ARCH]  # the PE header's machine type

# python-build-standalone (https://github.com/astral-sh/python-build-standalone): a relocatable CPython, the same
# version as the Mac app's (build-app.sh). The checksums are from that release's SHA256SUMS.
PY_VERSION = "3.14.7"
PY_RELEASE = "20260929"
PY_SHA256 = {
    "x64": "6378385d5e42ec0874656e5efd707fb92334a6972b1aca90fd254eb924a8f404",
    "arm64": "f373eec4bb1d46ea7c7bfca83880c06f79417c419ffd34c8d2643d59c4fe4ba1",
}[ARCH]
PY_FILE = f"cpython-{PY_VERSION}+{PY_RELEASE}-{RUST_TARGET}-install_only_stripped.tar.gz"  # (Rust's triples)
PY_URL = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PY_RELEASE}/{PY_FILE.replace('+', '%2B')}"


def say(text: str) -> None:
    print(f"> {text}", flush=True)


def die(text: str) -> None:
    print(f"x {text}", file=sys.stderr)
    sys.exit(1)


def run(args, **kwargs) -> None:
    kwargs.setdefault("check", True)
    subprocess.run(args, **kwargs)


def tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        die(f"Building needs {name} on the PATH.")
    return found


def rmtree(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


def download(url: str, sha256: str, what: str) -> Path:
    """Downloads url into build/cache once, and checks it against its pinned checksum every time."""
    import urllib.request
    CACHE.mkdir(parents=True, exist_ok=True)
    archive = CACHE / url.rsplit("/", 1)[1].replace("%2B", "+")
    if not archive.exists():
        say(f"Downloading {what} (once)…")
        part = archive.with_suffix(".part")
        with urllib.request.urlopen(url) as r, open(part, "wb") as f:
            shutil.copyfileobj(r, f)
        part.replace(archive)
    h = hashlib.sha256()
    with open(archive, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    if h.hexdigest() != sha256:
        archive.unlink()
        die(f"The downloaded {what} failed its checksum; try again.")
    return archive


def pe_machine(path: Path) -> int:
    with open(path, "rb") as f:
        head = f.read(4096)
    pe = int.from_bytes(head[0x3C:0x40], "little")
    return int.from_bytes(head[pe + 4:pe + 6], "little")


def pe_imports(path: Path) -> list[str]:
    """The DLLs a PE file links against, lower-case, as its import table names them."""
    data = path.read_bytes()

    def u32(at: int) -> int:
        return int.from_bytes(data[at:at + 4], "little")

    pe = u32(0x3C)
    opt = pe + 24
    size_of_optional = int.from_bytes(data[pe + 20:pe + 22], "little")
    sections = [opt + size_of_optional + 40 * i for i in range(int.from_bytes(data[pe + 6:pe + 8], "little"))]
    dirs = opt + (112 if data[opt:opt + 2] == b"\x0b\x02" else 96)  # (PE32+, or PE32)

    def offset(rva: int) -> int:
        for s in sections:
            va, size = u32(s + 12), max(u32(s + 8), u32(s + 16))
            if va <= rva < va + size:
                return u32(s + 20) + rva - va
        raise ValueError(f"{path.name}: RVA {rva:#x} is in no section")

    names, rva = [], u32(dirs + 8)  # the import directory (data directory 1)
    at = offset(rva) if rva else None
    while at is not None and u32(at + 12):
        start = offset(u32(at + 12))
        names.append(data[start:data.index(b"\0", start)].decode("ascii", "replace").lower())
        at += 20
    return names


def drop_stray_runtime(python: Path) -> None:
    """python-build-standalone's ARM runtime carries an x64 vcruntime140_1.dll (as of 3.14.7+20260929). An ARM process
    can't load it and nothing imports it, so it goes; and if something ever does import it, the build stops, since
    that file would then have to be an ARM one."""
    stray = python / "vcruntime140_1.dll"
    if ARCH != "arm64" or not stray.is_file() or pe_machine(stray) == MACHINE:
        return
    binaries = [python / "python.exe", *python.rglob("*.pyd"), *python.rglob("*.dll")]
    users = [p.name for p in binaries if p != stray and stray.name in pe_imports(p)]
    if users:
        die(f"{', '.join(users)} use {stray.name}, and the ARM runtime's copy of it is an x64 one")
    stray.unlink()
    say(f"Removed the runtime's unused x64 {stray.name}")


def semver_ok(version: str) -> bool:
    core, _, _ = version.partition("-")
    parts = core.split(".")
    return len(parts) == 3 and all(p.isdigit() for p in parts)


def trim(python: Path) -> None:
    """Drops what the app never uses from the Python runtime (as build-app.sh does)."""
    lib = python / "Lib"
    site = lib / "site-packages"
    for pattern in ("pip", "pip-*", "setuptools", "setuptools-*", "pkg_resources", "_distutils_hack", "distutils-precedence.pth"):
        for p in site.glob(pattern):
            rmtree(p)
    for name in ("test", "idlelib", "tkinter", "turtledemo", "ensurepip"):
        rmtree(lib / name)
    for name in ("tcl", "include", "libs", "Scripts"):
        rmtree(python / name)
    for p in [*(python / "DLLs").glob("_tkinter*"), *python.glob("tcl*.dll"), *python.glob("tk*.dll")]:
        rmtree(p)
    for p in [*site.rglob("tests"), *site.rglob("test")]:
        if p.is_dir():
            rmtree(p)
    for p in list(python.rglob("__pycache__")):
        rmtree(p)


def copy_app(into: Path) -> None:
    """The server's code: core/ and every module (Python files and any assets/ folders; no web sources or tests),
    with app.json and VERSION beside them, as build-app.sh does."""
    for top in ("core", "modules"):
        for src in (ROOT / top).rglob("*"):
            rel = src.relative_to(ROOT)
            parts = set(rel.parts)
            if not src.is_file() or parts & {"tests", "web", "__pycache__"}:
                continue
            if src.suffix != ".py" and "assets" not in parts:
                continue
            dest = into / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    shutil.copy2(ROOT / "app.json", into / "app.json")
    (into / "VERSION").write_text(VERSION + "\n", encoding="utf-8")


def stage() -> None:
    if not semver_ok(VERSION):
        die(f"Windows installers need a semver version (1.2.3, or 1.2.3-build.4), not {VERSION!r}")
    mac_only = [p for p in (ROOT / "scripts").glob("bundle-*.sh") if not p.with_suffix(".py").exists()]
    if mac_only:
        die(f"{', '.join(p.name for p in mac_only)} only runs on a Mac: add a matching .py for Windows")
    npm = tool("npm")
    say(f"Building {NAME} {VERSION} for Windows on {ARCH}")
    say("Building the web app…")
    if not (ROOT / "node_modules").is_dir():
        run([npm, "ci", "--silent"], cwd=ROOT)
    run([npm, "run", "-s", "build"], cwd=ROOT, stdout=subprocess.DEVNULL)

    archive = download(PY_URL, PY_SHA256, f"the Python runtime ({PY_VERSION})")
    rmtree(STAGE)
    STAGE.mkdir(parents=True)
    say("Unpacking the Python runtime…")
    with tarfile.open(archive) as tar:
        tar.extractall(STAGE, filter="data")  # -> build/windows/python
    python = STAGE / "python"
    py = python / "python.exe"
    if not py.is_file():
        die(f"No python.exe in {python}")

    # Wheels only: a package without one for this arch stops the build, rather than being compiled here unnoticed
    # (or an x64 copy being found later). PORTING.md's check of each native dependency is this, every build.
    say("Installing Python packages…")
    env = {**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1"}
    run([str(py), "-m", "pip", "install", "-q", "--no-compile", "--no-warn-script-location", "--only-binary=:all:", "-r", str(ROOT / "requirements.txt")], env=env)
    (STAGE / "bin").mkdir()
    for extra in sorted((ROOT / "scripts").glob("bundle-*.py")):
        say(f"Adding {extra.stem.removeprefix('bundle-')}…")
        run([str(py), str(extra)], env={**env, "STAGE": str(STAGE), "PY": str(py)})

    say("Trimming…")
    trim(python)
    drop_stray_runtime(python)
    copy_app(STAGE / "app")
    shutil.copytree(ROOT / "dist", STAGE / "ui")

    # The server starts the way the installed app starts it, before anything is packed.
    say("Checking the server imports…")
    # (with the environment the app gives it: this one's, without another Python's settings; server.rs)
    server_env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    server_env.update({f"{IDENTITY['envPrefix']}_DATA_DIR": str(ROOT / "build" / "import-check"), "PYTHONUTF8": "1",
                       "TRAILMIX_FAMILY_DIR": "off"})
    check = subprocess.run([str(py), "-E", "-s", "-c", "import core.server.app"], cwd=STAGE / "app", capture_output=True,
                           text=True, env=server_env)
    rmtree(ROOT / "build" / "import-check")
    if check.returncode != 0:
        die(f"The staged server doesn't import:\n{check.stderr[-3000:]}")
    # Windows on ARM emulates x64, so an x64 part in the ARM installer would pass everything else, only slowly.
    binaries = [py, *python.rglob("*.pyd"), *python.rglob("*.dll")]
    wrong = [str(p.relative_to(python)) for p in binaries if pe_machine(p) != MACHINE]
    if wrong:
        die(f"Not built for {ARCH}: {', '.join(wrong[:20])}")
    say(f"{len(binaries)} compiled files, all built for {ARCH}")

    # Compile ahead of time, never re-checked against the source: the app folder isn't written to while it runs,
    # and it starts faster.
    run([str(py), "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash", str(python / "Lib"), str(STAGE / "app")],
        stdout=subprocess.DEVNULL)
    size = sum(p.stat().st_size for p in STAGE.rglob("*") if p.is_file()) / 1e6
    say(f"Staged {STAGE} ({size:.0f} MB)")


def tauri_config() -> dict:
    """What this build adds to desktop/src-tauri/tauri.conf.json: who the app is, its version, and the staged
    files to put beside the program."""
    return {
        "productName": NAME,
        "mainBinaryName": SLUG,
        "version": VERSION,
        "identifier": IDENTITY.get("bundleId") or f"local.{IDENTITY['id']}.app",
        "bundle": {
            "resources": {
                "../../build/windows/python/": "python/",
                "../../build/windows/app/": "app/",
                "../../build/windows/ui/": "ui/",
                "../../build/windows/bin/": "bin/",
            },
        },
    }


def build_installer() -> None:
    npm = tool("npm")
    npx = tool("npx")
    tool("cargo")
    say("Building the desktop shell and the installer…")
    if not (DESKTOP / "node_modules").is_dir():
        run([npm, "ci", "--silent"], cwd=DESKTOP)
    override = ROOT / "build" / "windows-tauri.json"
    override.write_text(json.dumps(tauri_config()), encoding="utf-8")
    if shutil.which("rustup"):
        run(["rustup", "target", "add", RUST_TARGET], stdout=subprocess.DEVNULL)
    bundle = DESKTOP / "src-tauri" / "target" / RUST_TARGET / "release" / "bundle" / "nsis"
    rmtree(bundle)  # so an older build's installer is never picked up
    run([npx, "tauri", "build", "--target", RUST_TARGET, "--config", str(override)], cwd=DESKTOP)
    found = sorted(bundle.glob("*-setup.exe"))
    if not found:
        die("Tauri didn't make an installer")
    OUT.mkdir(parents=True, exist_ok=True)
    name = f"{SLUG}-{VERSION}-windows-{ARCH}.exe"
    target = OUT / name
    shutil.copy2(found[-1], target)
    # The updater checks a download against this before installing it, as the Mac's does.
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (OUT / f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding="utf-8")
    say(f"Built {target} ({target.stat().st_size / 1e6:.0f} MB)")


def main() -> None:
    if sys.platform != "win32":
        die("The Windows installer is built on Windows (CI: .github/workflows/desktop.yml).")
    stage()
    if "--stage-only" not in sys.argv:
        build_installer()


if __name__ == "__main__":
    main()
