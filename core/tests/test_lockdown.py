"""Lockdown: with it on, nothing leaves this computer. The guard below fails any request to another host, so a path
that forgot to ask would show up here. A module's own sync jobs are proved the same way in its tests."""
import httpx
import pytest

from core.server import ai, family, lockdown, ollama_setup, settings

CLOUD = ("anthropic", "openai", "gemini", "deepseek")


@pytest.fixture
def nothing_leaves(monkeypatch):
    """Records every request to a host other than this computer, and fails it."""
    sent: list[str] = []

    def guard(self, request, *a, **kw):
        if request.url.host not in ("localhost", "127.0.0.1", "::1"):
            sent.append(str(request.url))
        raise httpx.ConnectError("no network in tests")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guard)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guard)
    return sent


@pytest.fixture
def locked(nothing_leaves):
    keys = {f"ai.{p}_api_key": "key-for-the-test-1234" for p in CLOUD} | {"ai.custom_api_key": "k", "ai.custom_base_url": "https://llm.example.com/v1",
                                                                         "ai.custom_model": "m"}
    before = {k: settings.get_all()[k] for k in [*keys, lockdown.KEY, "ai.provider", "ai.fallback"]}
    settings.update({**keys, lockdown.KEY: True})
    yield nothing_leaves
    settings.update(before)


def test_it_is_off_until_chosen_and_the_family_shares_it(client):
    assert lockdown.on() is False and lockdown.blocked("Syncing") is None
    assert family.is_shared(lockdown.KEY)
    client.put("/api/settings", json={lockdown.KEY: True})
    try:
        assert lockdown.on() and client.get("/api/app").json()["lockdown"] is True
        assert "Syncing the Sheet is off while Lockdown is on" in lockdown.blocked("Syncing the Sheet")
    finally:
        client.put("/api/settings", json={lockdown.KEY: False})
    assert client.get("/api/app").json()["lockdown"] is False


@pytest.mark.parametrize("pid", [*CLOUD, "custom"])
def test_no_cloud_ai_answers_asks_or_lists_models(locked, client, pid):
    ok, why = ai.configured(pid, settings.section("ai"))
    assert not ok and why == lockdown.WHY
    with pytest.raises(ai.AIError, match="Lockdown"):
        ai.complete("hello", choice=pid)
    with pytest.raises(ai.AIError, match="Lockdown"):
        ai.structured("hello", None, ai._Probe, choice=pid)
    with pytest.raises(ai.AIError, match="Lockdown"):
        ai.list_models(pid)
    assert client.post(f"/api/ai/providers/{pid}/test").status_code == 502
    assert locked == []


def test_settings_say_why_each_provider_is_off(locked, client):
    shown = {p["id"]: p for p in client.get("/api/ai/providers").json()}
    for pid in (*CLOUD, "custom"):
        assert not shown[pid]["ready"] and "Lockdown" in shown[pid]["reason"]
    assert locked == []


def test_a_model_on_this_mac_still_answers(locked, monkeypatch):
    settings.update({"ai.provider": "ollama", "ai.ollama_url": "http://localhost:11434"})
    monkeypatch.setattr(ai, "_ollama_tags", lambda c: [{"name": "qwen2.5:7b", "details": {"parameter_size": "7B"}}])
    monkeypatch.setattr(ai, "_ollama", lambda cfg, prompt, system, keep: "hello from here")
    assert ai.complete("hi") == ("hello from here", "ollama")
    settings.update({"ai.custom_base_url": "http://localhost:1234/v1"})            # LM Studio on this Mac is also here
    assert ai.configured("custom", settings.section("ai"))[0]


def test_an_ollama_on_another_machine_is_not_here(locked):
    settings.update({"ai.ollama_url": "http://studio.local:11434"})
    try:
        assert ai.configured("ollama", settings.section("ai")) == (False, lockdown.WHY)
    finally:
        settings.update({"ai.ollama_url": "http://localhost:11434"})


def test_ollama_and_its_models_are_not_downloaded(locked, client, monkeypatch):
    monkeypatch.setattr(ollama_setup, "app_path", lambda: None)
    r = client.post("/api/ollama/install")
    assert r.status_code == 403 and "Turn off Lockdown" not in r.text and "Lockdown" in r.text
    r = client.post("/api/ollama/pull", json={"model": "qwen2.5:7b"})
    assert r.status_code == 403
    assert client.get("/api/ollama").json()["locked"] is True
    assert locked == [] and not ollama_setup._pull and not ollama_setup._install
