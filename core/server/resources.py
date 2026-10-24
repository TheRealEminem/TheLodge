"""What this Mac can do: a readout of memory, disk and chip, the gate that keeps a big local model from starving
everything else, and the advice setup shows. Ported from Trailmix, so a shared Settings can show either app's.

The gate (check) says "wait" only when going ahead would be a bad idea: the model can't fit in this Mac's memory at all,
the disk is too full for macOS to swap, or macOS already reports critical memory pressure. Anything short of that
runs, because macOS pages other memory out to disk and the work still gets done.
"""
import contextlib
import contextvars
import os
import re
import shutil
import subprocess
import sys

import psutil

from . import config

GB = 1024**3
# Extra free memory kept for macOS and other apps on top of what a model needs.
HEADROOM_GB = float(os.getenv("FAMILY_RAM_HEADROOM_GB", "2"))
# Short on free memory a model still runs (macOS swaps). That is only a bad idea when the disk is nearly full.
SWAP_DISK_FREE = float(os.getenv("FAMILY_SWAP_DISK_FREE", "0.10"))   # share of the disk that must be free
WAIT = "Waiting for memory"                                         # what every reason to wait starts with
psutil.cpu_percent(interval=None)                                   # prime: the first call always returns 0.0

_forced: contextvars.ContextVar[bool] = contextvars.ContextVar("memory_gate_forced", default=False)


@contextlib.contextmanager
def proceed_anyway():
    """Inside this, check() always says go: someone pressed "Proceed anyway"."""
    token = _forced.set(True)
    try:
        yield
    finally:
        _forced.reset(token)


def memory_pressure() -> int:
    """macOS's own verdict: 1 normal, 2 warning, 4 critical (1 where it can't be read)."""
    if sys.platform != "darwin":
        return 1
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                             capture_output=True, text=True, timeout=2).stdout.strip()
        return int(out or 1)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 1


def _disk():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(config.DATA_DIR)


def _disk_free_share() -> float:
    usage = _disk()
    return usage.free / usage.total if usage.total else 1.0


def chip() -> str:
    """e.g. "Apple M4" ("" where it can't be read)."""
    if sys.platform != "darwin":
        return ""
    try:
        return subprocess.run(["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True,
                              timeout=2).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def snapshot() -> dict:
    vm, swap, disk = psutil.virtual_memory(), psutil.swap_memory(), _disk()
    return {
        "chip": chip(),
        "ram_total_gb": round(vm.total / GB, 1),
        "ram_available_gb": round(vm.available / GB, 1),
        "ram_used_percent": vm.percent,
        "swap_used_gb": round(swap.used / GB, 1),
        "disk_free_gb": round(disk.free / GB, 1),
        "disk_free_percent": round(_disk_free_share() * 100),
        "memory_pressure": memory_pressure(),
        "headroom_gb": HEADROOM_GB,
    }


def has_room(required_gb: float) -> bool:
    """Enough free memory right now for a model this size, with the usual headroom (no swapping)."""
    return psutil.virtual_memory().available / GB >= required_gb + HEADROOM_GB


def check(required_gb: float, what: str) -> str | None:
    """None if the model can run now, otherwise a plain reason to wait (it starts with WAIT)."""
    if _forced.get():
        return None
    vm = psutil.virtual_memory()
    available, total = vm.available / GB, vm.total / GB
    needed = required_gb + HEADROOM_GB
    if available >= needed:
        return None
    what = what.lower()
    if required_gb > total - 2:
        return (f"{WAIT}: {what} needs about {required_gb:.1f} GB, more than this Mac can spare. "
                "Pick a smaller model in Settings, or proceed anyway.")
    if _disk_free_share() < SWAP_DISK_FREE:
        return (f"{WAIT}: {available:.1f} GB is free and {what} needs about {needed:.1f} GB, and with "
                f"under {SWAP_DISK_FREE:.0%} of the disk free macOS has little room to swap. "
                "Free up some disk space or close some apps, or proceed anyway.")
    if memory_pressure() >= 4:
        return (f"{WAIT}: macOS reports critical memory pressure and {what} needs about {needed:.1f} GB. "
                "It starts by itself when that eases. Close some apps, or proceed anyway.")
    return None


def device_advice(local_min_gb: float | None = None) -> dict:
    """What this Mac can comfortably do, for setup: {"verdict": "local" | "mixed" | "cloud", "chip", "ram_gb",
    "disk_free_gb", "notes": [...]}.

    local: everything an app asks of AI runs well here. mixed: the light jobs run here, and the heavy ones are better
    with a cloud AI. cloud: short on memory or disk for local models at all. `local_min_gb` is the memory an app's
    heaviest job needs to do well locally (app.json: localAiMinGb; 12 if it doesn't say)."""
    if local_min_gb is None:
        local_min_gb = float(config.IDENTITY.get("localAiMinGb", 12))
    vm, usage = psutil.virtual_memory(), _disk()
    ram, free = vm.total / GB, usage.free / GB
    share = usage.free / usage.total if usage.total else 1
    name = chip()
    notes: list[str] = []
    if ram < 8:
        verdict = "cloud"
        notes.append(f"{ram:.0f} GB of memory is too little to run an AI model beside your other apps. "
                     "A cloud AI (Claude, OpenAI or Gemini) is the better fit.")
    elif ram < local_min_gb:
        verdict = "mixed"
        notes.append(f"{ram:.0f} GB of memory runs a small AI model well for the lighter jobs. For the careful ones, "
                     "like reading a long document, a cloud AI does much better.")
    else:
        verdict = "local"
        notes.append(f"{ram:.0f} GB of memory leaves room for a larger local model, so everything can run on this Mac.")
    if re.search(r"\bM1\b", name) and ram < 12:
        notes.append("An M1 with this much memory is slow with local models; a cloud AI is the better fit.")
    if free < 8:
        verdict = "cloud"
        notes.append(f"Only {free:.0f} GB of disk is free. A local model takes 2 to 9 GB and macOS needs room to swap. "
                     "Free up space, or use a cloud AI.")
    elif free < 20 or share < SWAP_DISK_FREE:
        notes.append(f"{free:.0f} GB of disk free: enough for one small model, but a full disk leaves macOS little room "
                     "to swap, so keep an eye on it.")
    return {"verdict": verdict, "chip": name, "ram_gb": round(ram), "disk_free_gb": round(free), "notes": notes}
