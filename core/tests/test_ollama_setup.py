"""Ollama from inside the app: what's installed, the model this Mac should get, and the downloads, with the network faked."""
import json

import pytest

from core.server import ai, hardware, ollama_setup, resources

GB = resources.GB


@pytest.fixture(autouse=True)
def clean():
    ollama_setup._pull.clear()
    ollama_setup._install.clear()
    yield
    ollama_setup._pull.clear()
    ollama_setup._install.clear()


@pytest.mark.parametrize("ram, model", [(8, "qwen3.5:4b"), (14.9, "qwen3.5:4b"), (16, "qwen3.5:9b"), (64, "qwen3.5:9b")])
def test_the_model_follows_the_macs_memory(monkeypatch, ram, model):
    monkeypatch.setattr(resources, "snapshot", lambda: {"ram_total_gb": ram})
    monkeypatch.setattr(hardware, "profile", lambda: {"ai_runs_on": "unified", "ai_memory_gb": ram * 0.7})
    assert ollama_setup.recommended() == model


def test_status_says_what_is_there(client, monkeypatch):
    monkeypatch.setattr(ollama_setup, "app_path", lambda: None)
    monkeypatch.setattr(ai, "_ollama_tags", lambda c: [])
    monkeypatch.setattr(ollama_setup, "_reachable", lambda url: False)
    s = client.get("/api/ollama").json()
    assert s["installed"] is False and s["reachable"] is False and s["models"] == [] and s["recommended"].startswith("qwen3.5")
    monkeypatch.setattr(ollama_setup, "app_path", lambda: "/Applications/Ollama.app")
    monkeypatch.setattr(ai, "_ollama_tags", lambda c: [{"name": "qwen2.5:7b", "details": {"parameter_size": "7B"}}])
    s = client.get("/api/ollama").json()
    assert s["installed"] and s["reachable"] and s["models"] == ["qwen2.5:7b"] and s["using"] == "qwen2.5:7b"


def test_a_model_is_pulled_with_progress(client, monkeypatch):
    lines = [json.dumps(m) for m in ({"status": "pulling manifest"}, {"status": "pulling", "total": 100, "completed": 40},
                                     {"status": "pulling", "total": 100, "completed": 100}, {"status": "success"})]

    class Stream:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def iter_lines(self): return iter(lines)

    monkeypatch.setattr(ollama_setup.httpx, "stream", lambda *a, **kw: Stream())

    class Immediately:
        def __init__(self, target, args, **kw): self.target, self.args = target, args
        def start(self): self.target(*self.args)

    monkeypatch.setattr(ollama_setup.threading, "Thread", Immediately)
    assert client.post("/api/ollama/pull", json={"model": ""}).json() == {"started": True}
    pull = client.get("/api/ollama").json()["pull"]
    assert pull["model"] == ollama_setup.recommended() and pull["active"] is False and pull["progress"] == 1.0 and pull["error"] is None


def test_a_failed_pull_says_so(client, monkeypatch):
    class Stream:
        status_code = 500
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(ollama_setup.httpx, "stream", lambda *a, **kw: Stream())

    class Immediately:
        def __init__(self, target, args, **kw): self.target, self.args = target, args
        def start(self): self.target(*self.args)

    monkeypatch.setattr(ollama_setup.threading, "Thread", Immediately)
    client.post("/api/ollama/pull", json={"model": "nope:1b"})
    assert "Couldn't download nope:1b" in client.get("/api/ollama").json()["pull"]["error"]


def test_only_a_download_signed_by_ollama_is_installed(tmp_path, monkeypatch):
    app = tmp_path / "Ollama.app"
    app.mkdir()
    class Done:
        def __init__(self, returncode=0, stderr=""): self.returncode, self.stderr = returncode, stderr

    monkeypatch.setattr(ollama_setup.subprocess, "run", lambda cmd, **kw: Done(0, "TeamIdentifier=SOMEONEELSE"))
    with pytest.raises(RuntimeError, match="isn't signed by Ollama"):
        ollama_setup._verify(app)
    monkeypatch.setattr(ollama_setup.subprocess, "run", lambda cmd, **kw: Done(1))
    with pytest.raises(RuntimeError, match="failed its signature check"):
        ollama_setup._verify(app)
    monkeypatch.setattr(ollama_setup.subprocess, "run", lambda cmd, **kw: Done(0, f"TeamIdentifier={ollama_setup.OLLAMA_TEAM}"))
    ollama_setup._verify(app)


def windows_check(monkeypatch, stdout="", stderr="", returncode=0):
    """Runs _verify_windows against a stand-in for PowerShell; gives back what it was started with."""
    seen = {}

    class Done:
        def __init__(self):
            self.stdout, self.stderr, self.returncode = stdout, stderr, returncode

    def run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return Done()

    monkeypatch.setattr(ollama_setup.subprocess, "run", run)
    return seen


def test_windows_powershell_gets_no_module_path_from_powershell_7(tmp_path, monkeypatch):
    """Started from PowerShell 7, the app inherits a PSModulePath Windows PowerShell can't load its Security module from."""
    monkeypatch.setenv("PSModulePath", r"C:\Program Files\PowerShell\7\Modules")
    seen = windows_check(monkeypatch, stdout="Valid\nCN=Ollama Inc.\n")
    ollama_setup._verify_windows(tmp_path / "OllamaSetup.exe")
    assert not any(name.upper() == "PSMODULEPATH" for name in seen["env"])
    assert seen["env"].get("PATH") == ollama_setup.os.environ.get("PATH")


def test_a_windows_download_is_only_run_when_valid_and_ollamas(tmp_path, monkeypatch):
    setup = tmp_path / "OllamaSetup.exe"
    windows_check(monkeypatch, stdout="Valid\nCN=Ollama Inc.\n")
    ollama_setup._verify_windows(setup)
    windows_check(monkeypatch, stdout="Valid\nCN=Someone Else\n")
    with pytest.raises(RuntimeError, match="isn't signed by Ollama"):
        ollama_setup._verify_windows(setup)
    windows_check(monkeypatch, stdout="HashMismatch\nCN=Ollama Inc.\n")
    with pytest.raises(RuntimeError, match="failed its signature check"):
        ollama_setup._verify_windows(setup)


def test_a_check_that_says_nothing_is_refused_and_logs_why(tmp_path, monkeypatch, caplog):
    windows_check(monkeypatch, stderr="the module could not be loaded", returncode=1)
    with pytest.raises(RuntimeError, match="failed its signature check"), caplog.at_level("WARNING", logger="core.ollama"):
        ollama_setup._verify_windows(tmp_path / "OllamaSetup.exe")
    assert "the module could not be loaded" in caplog.text


# ── Offering a newer model ──────────────────────────────────────────────

def tag(name, size="7B"):
    return {"name": name, "details": {"parameter_size": size}}


@pytest.fixture
def big_mac(monkeypatch):
    monkeypatch.setattr(resources, "snapshot", lambda: {"ram_total_gb": 16})
    monkeypatch.setattr(hardware, "profile", lambda: {"ai_runs_on": "unified", "ai_memory_gb": 11})


def cfg(**over):
    return {"ollama_model": "", "model_suggestion_dismissed": "", **over}


def test_a_legacy_model_is_offered_the_recommended_one(big_mac):
    assert ollama_setup.suggestion(cfg(), [tag("qwen2.5:7b")]) == {"model": "qwen3.5:9b", "replaces": "qwen2.5:7b"}
    assert ollama_setup.suggestion(cfg(), [tag("qwen3:8b", "8B")]) == {"model": "qwen3.5:9b", "replaces": "qwen3:8b"}


@pytest.mark.parametrize("tags, settings_", [
    ([tag("qwen3.5:9b", "9B")], {}),                                                 # already the best
    ([tag("qwen3.5:9b", "9B"), tag("qwen2.5:7b")], {}),                              # has it as well
    ([tag("my-own-finetune:7b")], {}),                                               # brought their own: never nagged
    ([tag("qwen2.5:7b")], {"ollama_model": "qwen2.5:7b"}),                           # chose it themselves
    ([tag("qwen2.5:7b")], {"model_suggestion_dismissed": "qwen3.5:9b"}),             # said not now
    ([tag("nomic-embed-text:latest", "137M")], {}),                                  # only an embedding model
    ([], {}),
])
def test_when_nothing_is_offered(big_mac, tags, settings_):
    assert ollama_setup.suggestion(cfg(**settings_), tags) is None


def test_a_different_recommendation_is_offered_again_after_not_now(big_mac, monkeypatch):
    dismissed = cfg(model_suggestion_dismissed="qwen3.5:9b")
    assert ollama_setup.suggestion(dismissed, [tag("qwen2.5:7b")]) is None
    monkeypatch.setattr(ollama_setup, "recommended", lambda: "qwen4:9b")
    monkeypatch.setitem(ollama_setup.model_catalog.__dict__, "FAMILIES", [{"family": "qwen4", "status": "recommended", "thinking": False}, *ollama_setup.model_catalog.FAMILIES])
    assert ollama_setup.suggestion(dismissed, [tag("qwen2.5:7b")]) == {"model": "qwen4:9b", "replaces": "qwen2.5:7b"}


def test_the_status_carries_the_offer_and_not_now_is_remembered(client, monkeypatch, big_mac):
    monkeypatch.setattr(ollama_setup, "app_path", lambda: "/Applications/Ollama.app")
    monkeypatch.setattr(ai, "_ollama_tags", lambda c: [tag("qwen2.5:7b")])
    assert client.get("/api/ollama").json()["suggestion"] == {"model": "qwen3.5:9b", "replaces": "qwen2.5:7b"}
    assert client.post("/api/ollama/dismiss-suggestion", json={"model": "qwen3.5:9b"}).json() == {"ok": True}
    assert client.get("/api/ollama").json()["suggestion"] is None
