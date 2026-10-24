"""Ollama from inside the app: what's installed, the model this Mac should get, and the downloads, with the network faked."""
import json

import pytest

from core.server import ai, ollama_setup, resources

GB = resources.GB


@pytest.fixture(autouse=True)
def clean():
    ollama_setup._pull.clear()
    ollama_setup._install.clear()
    yield
    ollama_setup._pull.clear()
    ollama_setup._install.clear()


@pytest.mark.parametrize("ram, model", [(8, "qwen2.5:3b"), (14.9, "qwen2.5:3b"), (16, "qwen2.5:7b"), (64, "qwen2.5:7b")])
def test_the_model_follows_the_macs_memory(monkeypatch, ram, model):
    monkeypatch.setattr(resources, "snapshot", lambda: {"ram_total_gb": ram})
    assert ollama_setup.recommended() == model


def test_status_says_what_is_there(client, monkeypatch):
    monkeypatch.setattr(ollama_setup, "app_path", lambda: None)
    monkeypatch.setattr(ai, "_ollama_tags", lambda c: [])
    monkeypatch.setattr(ollama_setup, "_reachable", lambda url: False)
    s = client.get("/api/ollama").json()
    assert s["installed"] is False and s["reachable"] is False and s["models"] == [] and s["recommended"].startswith("qwen2.5")
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
