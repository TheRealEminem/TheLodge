"""What this computer has for running AI models, and the advice drawn from it: a local model is recommended only where a
chip Ollama supports will run it. The parsers take plain text and values, so these read any system's output on any system."""
from collections import namedtuple
from pathlib import Path

import pytest

from core.server import computer, hardware, ollama_setup, resources

GB = 1024**3
Mem = namedtuple("Mem", "total available percent")
Disk = namedtuple("Disk", "total used free")


def test_windows_graphics_come_from_the_display_class_with_their_real_memory():
    devices = [
        # qwMemorySize is right past 4 GB (WMI's AdapterRAM stops at 4).
        {"DriverDesc": "NVIDIA GeForce RTX 4070", "ProviderName": "NVIDIA", "MatchingDeviceId": "pci\\ven_10de&dev_2786",
         "HardwareInformation.qwMemorySize": 12 * GB},
        # Some drivers store it as bytes.
        {"DriverDesc": "AMD Radeon RX 7900 XTX", "ProviderName": "Advanced Micro Devices, Inc.",
         "HardwareInformation.qwMemorySize": (24 * GB).to_bytes(8, "little")},
        {"DriverDesc": "Intel(R) UHD Graphics 770", "ProviderName": "Intel Corporation",
         "HardwareInformation.MemorySize": 128 * 1024**2},
        {"DriverDesc": "Microsoft Basic Display Adapter", "ProviderName": "Microsoft"},
        {"DriverDesc": "Parsec Virtual Display Adapter", "ProviderName": "Parsec Cloud, Inc."},
        {"ProviderName": "NVIDIA"},  # no name: not a device worth listing
    ]
    gpus = hardware.windows_gpus(devices)
    assert [(g["name"], g["vendor"], g["vram_gb"]) for g in gpus] == [
        ("NVIDIA GeForce RTX 4070", "nvidia", 12.0),
        ("AMD Radeon RX 7900 XTX", "amd", 24.0),
        ("Intel(R) UHD Graphics 770", "intel", 0.1),
    ]
    assert hardware.windows_npu([{}, {"DriverDesc": " Intel(R)  AI Boost "}]) == "Intel(R) AI Boost"
    assert hardware.windows_npu([]) == ""


def test_linux_reads_the_cpu_nvidia_smi_drm_cards_and_accel_npus():
    assert hardware.linux_cpu("processor\t: 0\nmodel name\t: AMD Ryzen 9  7950X 16-Core Processor\n") == \
        "AMD Ryzen 9 7950X 16-Core Processor"
    assert hardware.linux_cpu("processor : 0\nHardware : BCM2835\n") == "BCM2835"
    assert hardware.linux_cpu("processor : 0\nCPU implementer : 0x41\n") == ""
    assert [(g["name"], g["vram_gb"]) for g in hardware.nvidia_smi_gpus("NVIDIA GeForce RTX 4090, 24564\nnonsense\n")] == \
        [("NVIDIA GeForce RTX 4090", 24.0)]
    cards = [{"vendor": "0x1002", "vram": str(16 * GB)}, {"vendor": "0x8086", "vram": ""}, {"vendor": "0x1af4"}]
    assert [(g["name"], g["vendor"], g["vram_gb"]) for g in hardware.linux_drm_gpus(cards)] == \
        [("AMD graphics", "amd", 16.0), ("Intel graphics", "intel", None)]
    assert hardware.linux_npu(["intel_vpu"]) == "Intel NPU"
    assert hardware.linux_npu(["something_new"]) == "NPU"
    assert hardware.linux_npu([]) == ""


def test_apple_silicon_shares_its_memory_with_its_gpu_and_an_intel_mac_has_none_to_use():
    cpu, gpus, npu = hardware.mac_hardware("Apple M4 Pro")
    assert (cpu, npu) == ("Apple M4 Pro", "Apple Neural Engine")
    assert gpus[0]["unified"] and gpus[0]["vendor"] == "apple"
    assert hardware.mac_hardware("Intel(R) Core(TM) i7-8850H CPU @ 2.60GHz") == ("Intel(R) Core(TM) i7-8850H CPU @ 2.60GHz", [], "")


def card(name, gb):
    return hardware.windows_gpus([{"DriverDesc": name, "HardwareInformation.qwMemorySize": int(gb * GB)}])


def test_only_a_supported_card_with_enough_memory_counts_as_room_for_a_model():
    assert hardware.ai_memory(16, hardware.mac_hardware("Apple M4")[1]) == (11.2, "unified")
    rtx = card("NVIDIA GeForce RTX 4070", 12)
    assert hardware.ai_memory(64, rtx) == (12.0, "gpu")
    assert hardware.ai_memory(64, card("AMD Radeon RX 7600", 8)) == (8.0, "gpu")
    # An integrated chip, a small card, one Ollama doesn't run models on, a Snapdragon's, or none: the CPU.
    for gpus in (card("NVIDIA GeForce MX450", 2), card("Intel(R) Arc(TM) A770", 16), card("Qualcomm(R) Adreno(TM) X1-85 GPU", 8), []):
        assert hardware.ai_memory(32, gpus)[1] == "cpu"
    assert hardware.gpu_label(rtx + card("Intel(R) Arc(TM) A770", 16)) == "NVIDIA GeForce RTX 4070 (12 GB)"
    assert hardware.gpu_label(card("Intel(R) Arc(TM) A770", 16)) == ""


def test_the_profile_reads_this_computer_and_survives_a_reader_that_fails(monkeypatch):
    p = hardware.profile()
    assert {"os", "arch", "cpu", "cores", "ram_gb", "gpus", "npu", "ai_memory_gb", "ai_runs_on"} <= set(p)
    assert p["ram_gb"] > 0 and p["os"] == computer.OS

    def broken():
        raise PermissionError("no access")

    monkeypatch.setitem(hardware._READERS, p["os"], broken)
    hardware.profile.cache_clear()
    try:
        fallback = hardware.profile()
        assert fallback["cpu"] == "" and fallback["gpus"] == [] and fallback["ai_runs_on"] == "cpu"
    finally:
        hardware.profile.cache_clear()


# ── The rule ─────────────────────────────────────────────────────────

@pytest.fixture
def machine(monkeypatch):
    """machine(ram, gpus, npu, disk_free): the advice for a computer with these, needing 24 GB (The Lodge's figure)."""
    def make(ram=32, gpus=(), npu="", cpu="AMD Ryzen 7", disk_free=400, local_min_gb=24):
        gpus = list(gpus)
        room, runs_on = hardware.ai_memory(ram, gpus)
        profile = {"cpu": cpu, "gpus": gpus, "npu": npu, "ai_memory_gb": room, "ai_runs_on": runs_on}
        monkeypatch.setattr(hardware, "profile", lambda: profile)
        monkeypatch.setattr(resources.psutil, "virtual_memory", lambda: Mem(ram * GB, ram * GB / 2, 50.0))
        monkeypatch.setattr(resources, "_disk", lambda: Disk(1000 * GB, (1000 - disk_free) * GB, disk_free * GB))
        monkeypatch.setattr(resources, "snapshot", lambda: {"ram_total_gb": ram})
        return resources.device_advice(local_min_gb=local_min_gb)
    return make


@pytest.mark.parametrize("ram", [8, 32, 128])
def test_without_a_chip_for_it_the_advice_is_cloud_whatever_the_memory(machine, ram):
    got = machine(ram=ram)
    assert got["verdict"] == "cloud" and got["gpu"] == ""
    assert "too slow to be useful" in got["notes"][0] and "cloud AI" in got["notes"][0]


def test_integrated_graphics_an_unsupported_card_and_an_npu_are_named_but_dont_count(machine):
    got = machine(gpus=card("Intel(R) UHD Graphics 770", 0.5), npu="Intel(R) AI Boost")
    assert got["verdict"] == "cloud" and got["npu"] == "Intel(R) AI Boost"
    assert "Intel(R) UHD Graphics 770 isn't one" in got["notes"][0] and "Intel(R) AI Boost isn't something" in got["notes"][0]
    assert machine(gpus=card("Intel(R) Arc(TM) A770", 16))["verdict"] == "cloud"
    assert machine(gpus=card("Qualcomm(R) Adreno(TM) X1-85 GPU", 8), npu="Snapdragon(R) X Elite NPU")["verdict"] == "cloud"


@pytest.mark.parametrize("gb, verdict", [(4, "mixed"), (8, "mixed"), (16, "local"), (24, "local")])
def test_a_supported_card_is_judged_by_its_own_memory_in_the_macs_terms(machine, gb, verdict):
    got = machine(ram=16, gpus=card("NVIDIA GeForce RTX 4070", gb))   # main memory doesn't decide it
    assert got["verdict"] == verdict and got["gpu"] == f"NVIDIA GeForce RTX 4070 ({gb} GB)"
    assert got["notes"][0].startswith(f"The NVIDIA GeForce RTX 4070 ({gb} GB) graphics card")


def test_a_card_with_little_main_memory_or_disk_is_still_cloud(machine):
    assert machine(ram=6, gpus=card("NVIDIA GeForce RTX 4070", 12))["verdict"] == "cloud"
    assert machine(disk_free=4, gpus=card("NVIDIA GeForce RTX 4070", 12))["verdict"] == "cloud"


@pytest.mark.parametrize("ram, verdict", [(6, "cloud"), (16, "mixed"), (24, "local"), (64, "local")])
def test_apple_silicon_is_still_judged_by_its_memory(machine, ram, verdict):
    got = machine(ram=ram, gpus=hardware.mac_hardware("Apple M4")[1], npu="Apple Neural Engine", cpu="Apple M4")
    assert got["verdict"] == verdict and got["gpu"] == ""


def test_the_room_and_the_model_follow_the_chip_not_the_memory(machine):
    machine(ram=128)                                               # plenty of memory, no chip
    assert resources.local_memory_gb() == 0 and ollama_setup.recommended() == ollama_setup.RECOMMENDED_SMALL
    machine(ram=16, gpus=card("NVIDIA GeForce RTX 4090", 24))      # 24 GB on a card goes as far as 36 GB on a Mac
    assert resources.local_memory_gb() == 36 and ollama_setup.recommended() == ollama_setup.RECOMMENDED_BIG
    machine(ram=64, gpus=card("NVIDIA GeForce GTX 1650", 4))
    assert resources.local_memory_gb() == 6 and ollama_setup.recommended() == ollama_setup.RECOMMENDED_SMALL
    machine(ram=64, gpus=card("NVIDIA GeForce RTX 3060", 8))
    assert resources.local_memory_gb() == 12 and ollama_setup.recommended() == ollama_setup.RECOMMENDED_BIG


# ── Ollama on Windows and Linux ──────────────────────────────────────

def test_only_a_valid_signature_of_ollamas_is_run_on_windows():
    assert ollama_setup.signature_problem("Valid", "CN=Ollama Inc., O=Ollama Inc., C=US") is None
    assert "signature check" in ollama_setup.signature_problem("HashMismatch", "CN=Ollama Inc.")
    assert "signature check" in ollama_setup.signature_problem("NotSigned", "")
    assert "isn't signed by Ollama" in ollama_setup.signature_problem("Valid", "CN=Someone Else")


def test_the_signature_check_finds_powershell_without_the_path(monkeypatch):
    """The installed app's server has a short PATH without PowerShell on it: that stopped every install on Windows."""
    seen = {}

    class Done:
        stdout = "Valid\nCN=Ollama Inc.\n"

    def run(cmd, **kw):
        seen["program"] = cmd[0]
        return Done()

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(ollama_setup.subprocess, "run", run)
    ollama_setup._verify_windows(Path("OllamaSetup.exe"))
    assert "System32" in seen["program"] and seen["program"].endswith("powershell.exe")


def test_linux_shows_what_to_run_and_nothing_elsewhere(monkeypatch):
    monkeypatch.setattr(ollama_setup.sys, "platform", "linux")
    missing = ollama_setup._linux_commands(False)
    assert "install.sh" in missing["install_command"] and missing["start_command"] is None and missing["install_page"]
    monkeypatch.setattr(ollama_setup, "LINUX_SERVICE_FILES", [])
    assert ollama_setup._linux_commands(True) == {"install_command": None, "install_page": ollama_setup.LINUX_INSTALL_PAGE, "start_command": "ollama serve"}
    monkeypatch.setattr(ollama_setup.sys, "platform", "win32")
    assert ollama_setup._linux_commands(False) == {"install_command": None, "install_page": None, "start_command": None}
