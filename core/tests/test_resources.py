"""What this Mac can do, and the gate that makes a local model wait for memory instead of starving the Mac.
Memory and disk are faked, so these say the same thing on any machine."""
from collections import namedtuple

import httpx
import pytest
from pydantic import BaseModel

from core.server import ai, ai_adapters, db, jobs, resources, schedule

GB = resources.GB
Mem = namedtuple("Mem", "total available percent")
Disk = namedtuple("Disk", "total used free")


@pytest.fixture
def mac(monkeypatch):
    """mac(ram=16, free_ram=…, disk_free=…, pressure=1): a Mac with those numbers (all in GB)."""
    def make(ram=16, free_ram=8, disk_free=100, disk_total=500, pressure=1, name="Apple M4"):
        monkeypatch.setattr(resources.psutil, "virtual_memory", lambda: Mem(ram * GB, free_ram * GB, 50.0))
        monkeypatch.setattr(resources, "_disk", lambda: Disk(disk_total * GB, (disk_total - disk_free) * GB, disk_free * GB))
        monkeypatch.setattr(resources, "memory_pressure", lambda: pressure)
        monkeypatch.setattr(resources, "chip", lambda: name)
    return make


def test_a_model_that_fits_goes_ahead(mac):
    mac(ram=16, free_ram=8)
    assert resources.check(5, "the model") is None


def test_short_of_memory_still_goes_ahead_when_the_mac_can_swap(mac):
    mac(ram=16, free_ram=3, disk_free=100)
    assert resources.check(5, "the model") is None


@pytest.mark.parametrize("numbers, says", [
    (dict(ram=8, free_ram=1), "more than this Mac can spare"),
    (dict(ram=16, free_ram=3, disk_free=20, disk_total=500), "little room to swap"),
    (dict(ram=16, free_ram=3, pressure=4), "critical memory pressure"),
])
def test_each_reason_to_wait_is_said_plainly(mac, numbers, says):
    mac(**numbers)
    why = resources.check(9 if numbers["ram"] == 8 else 5, "The model qwen2.5:7b")
    assert why.startswith(resources.WAIT) and says in why and "proceed anyway" in why


def test_proceed_anyway_stands_aside(mac):
    mac(ram=8, free_ram=1)
    with resources.proceed_anyway():
        assert resources.check(9, "the model") is None
    assert resources.check(9, "the model")


@pytest.mark.parametrize("ram, disk, verdict", [(6, 200, "cloud"), (8, 200, "mixed"), (16, 200, "mixed"),
                                                (24, 200, "local"), (32, 4, "cloud"), (16, 17, "mixed")])
def test_the_advice_follows_memory_and_disk(mac, ram, disk, verdict):
    mac(ram=ram, disk_free=disk)
    got = resources.device_advice(local_min_gb=20)
    assert got["verdict"] == verdict and got["chip"] == "Apple M4" and got["ram_gb"] == ram and got["notes"]


def test_the_system_readout_is_served(client, mac):
    mac(ram=16, free_ram=6)
    got = client.get("/api/system").json()
    assert got["snapshot"]["ram_total_gb"] == 16 and got["snapshot"]["ram_available_gb"] == 6
    assert got["advice"]["verdict"] in ("local", "mixed", "cloud")


# ── The gate in the AI layer ──────────────────────────────────────────

class Out(BaseModel):
    answer: str = ""


@pytest.fixture
def local_model(monkeypatch):
    """An Ollama on this Mac with a 6 GB model, not loaded; calls to it are recorded."""
    cfg = dict(ai.DEFAULTS, provider="ollama")
    real_section = ai.settings.section
    monkeypatch.setattr(ai.settings, "section", lambda namespace: cfg if namespace == "ai" else real_section(namespace))
    monkeypatch.setattr(ai, "_ollama_tags", lambda c: [{"name": "qwen2.5:7b", "size": 6 * GB, "details": {"parameter_size": "7B"}}])
    monkeypatch.setattr(ai, "_ollama_loaded", lambda c, m: False)
    calls = []

    def post(url, **kw):
        calls.append(url)
        return httpx.Response(200, json={"message": {"content": '{"answer": "ok"}'}, "response": "ok", "done_reason": "stop"},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(ai_adapters.httpx, "post", post)
    monkeypatch.setattr(ai.httpx, "post", post)
    return calls


def test_a_local_model_waits_with_a_reason_when_there_is_no_room(mac, local_model):
    mac(ram=8, free_ram=1)
    with pytest.raises(ai.AIError) as e:
        ai.structured("hi", None, Out)
    assert e.value.provider_down and str(e.value).startswith("Ollama: " + resources.WAIT)
    assert local_model == []                                   # nothing was sent to the model


def test_it_runs_when_there_is_room_and_the_answer_is_capped(mac, local_model, monkeypatch):
    mac(ram=16, free_ram=10)
    sent = {}
    real = ai_adapters.httpx.post
    monkeypatch.setattr(ai_adapters.httpx, "post", lambda url, **kw: sent.update(kw) or real(url, **kw))
    got, provider = ai.structured("hi", None, Out)
    assert got.answer == "ok" and provider == "ollama"
    assert sent["json"]["options"]["num_predict"] == ai_adapters.OLLAMA_OUTPUT_BUDGET
    assert sent["timeout"].read == ai_adapters.OLLAMA_TIMEOUT_SECONDS


def test_a_model_already_in_memory_costs_nothing_more(mac, local_model, monkeypatch):
    mac(ram=8, free_ram=1)
    monkeypatch.setattr(ai, "_ollama_loaded", lambda c, m: True)
    assert ai.structured("hi", None, Out)[0].answer == "ok"


def test_another_machines_ollama_needs_no_room_here(mac, local_model, monkeypatch):
    mac(ram=8, free_ram=1)
    cfg = dict(ai.DEFAULTS, provider="ollama", ollama_url="http://studio.local:11434")
    real_section = ai.settings.section
    monkeypatch.setattr(ai.settings, "section", lambda namespace: cfg if namespace == "ai" else real_section(namespace))
    assert ai.structured("hi", None, Out)[0].answer == "ok"


def test_plain_text_calls_wait_and_are_capped_too(mac, local_model):
    mac(ram=8, free_ram=1)
    with pytest.raises(ai.AIError, match=resources.WAIT):
        ai.complete("hi")
    mac(ram=16, free_ram=10)
    assert ai.complete("hi")[0] == "ok"


# ── Jobs wait, then start by themselves ───────────────────────────────

def test_a_job_that_waits_for_memory_starts_by_itself_when_there_is_room(mac, local_model):
    ran = []

    def handler(job):
        try:
            ai.structured("hi", None, Out)
        except ai.AIError as e:
            raise jobs.Wait(str(e)) from e
        ran.append(job.id)

    jobs.register("probe", "think", handler)
    mac(ram=8, free_ram=1)
    job_id = jobs.enqueue("probe", "think", "t1")
    jobs.drain()
    row = db.one("SELECT status, wait_reason FROM core_jobs WHERE id = ?", (job_id,))
    assert row["status"] == "waiting" and row["wait_reason"].startswith("Ollama: " + resources.WAIT) and not ran

    schedule.tick()                                              # still no room: it stays parked
    jobs.drain()
    assert db.one("SELECT status FROM core_jobs WHERE id = ?", (job_id,))["status"] == "waiting"

    mac(ram=16, free_ram=10)                                     # memory frees up
    schedule.tick()
    jobs.drain()
    assert db.one("SELECT status FROM core_jobs WHERE id = ?", (job_id,))["status"] == "done" and ran == [job_id]


def test_proceed_anyway_runs_a_waiting_job_regardless(mac, local_model):
    ran = []

    def handler(job):
        try:
            ai.structured("hi", None, Out)
        except ai.AIError as e:
            raise jobs.Wait(str(e)) from e
        ran.append(job.id)

    jobs.register("probe", "think", handler)
    mac(ram=8, free_ram=1)
    job_id = jobs.enqueue("probe", "think", "t2")
    jobs.drain()
    jobs.go(job_id, force=True)
    jobs.drain()
    assert ran == [job_id]
