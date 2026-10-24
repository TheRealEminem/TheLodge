"""The first run and choosing where AI runs: new or existing installs, what each path does to the jobs, and what the
setup screen is told about this Mac and every module's AI work."""
import pytest

from core.server import ai, lockdown, module, resources, settings, setup


@pytest.fixture
def jobs_module(monkeypatch):
    """A stand-in module with one heavy and one light AI job."""
    stand_in = module.Module(id="setupprobe", name="Setup probe", ai_jobs={
        "read": {"label": "Reading", "hint": "Reads what you add.", "weight": "heavy"},
        "sort": {"label": "Sorting", "weight": "light", "choice": lambda: "rules"},
    })
    monkeypatch.setitem(module._loaded, "setupprobe", stand_in)


@pytest.fixture(autouse=True)
def restore_ai():
    keys = ["ai.path", "ai.provider", "ai.heavy_provider", "ai.fallback", "ai.anthropic_api_key", lockdown.KEY, setup.DONE]
    before = {k: settings.get_all()[k] for k in keys}
    yield
    settings.update(before)


def test_auto_follows_the_app_wide_choice_unless_heavy_jobs_went_to_the_cloud():
    settings.update({"ai.provider": "ollama", "ai.heavy_provider": "auto"})
    assert ai.resolve("auto", "heavy") == "auto" and ai.resolve("auto", "light") == "auto"       # both follow ai.provider
    settings.update({"ai.heavy_provider": "anthropic"})
    assert ai.resolve("auto", "heavy") == "anthropic" and ai.resolve("auto", "light") == "auto"   # light stays "the app's"
    assert ai.resolve("gemini", "heavy") == "gemini" and ai.resolve("rules", "heavy") == "rules"  # a named one is kept


def test_each_path_places_the_jobs(client):
    settings.update({"ai.anthropic_api_key": "sk-ant-test-1234567890", lockdown.KEY: True})
    out = client.put("/api/setup/path", json={"path": "mixed", "cloud": "anthropic"}).json()
    assert out["path"] == "mixed" and not lockdown.on()                    # leaving this Mac, so Lockdown is off
    assert settings.get_all()["ai.provider"] == "ollama" and settings.get_all()["ai.heavy_provider"] == "anthropic"

    client.put("/api/setup/path", json={"path": "cloud", "cloud": "anthropic"})
    assert settings.get_all()["ai.provider"] == "anthropic" and settings.get_all()["ai.heavy_provider"] == "auto"

    settings.update({lockdown.KEY: True})
    client.put("/api/setup/path", json={"path": "local"})
    assert settings.get_all()["ai.provider"] == "ollama" and settings.get_all()["ai.heavy_provider"] == "auto"
    assert lockdown.on()                                                   # "on this Mac" never turns Lockdown off


@pytest.mark.parametrize("body", [{"path": "nowhere"}, {"path": "mixed"}, {"path": "cloud", "cloud": "ollama"},
                                  {"path": "cloud", "cloud": "nothing"}])
def test_a_path_needs_a_real_cloud_provider_when_it_uses_one(client, body):
    before = settings.get_all()["ai.provider"]
    assert client.put("/api/setup/path", json=body).status_code == 400
    assert settings.get_all()["ai.provider"] == before


def test_setup_lists_every_modules_jobs_and_where_each_runs(client, jobs_module, monkeypatch):
    settings.update({"ai.anthropic_api_key": "sk-ant-test-1234567890"})
    monkeypatch.setattr(ai, "_ollama_tags", lambda c: [{"name": "qwen2.5:7b", "details": {"parameter_size": "7B"}}])
    client.put("/api/setup/path", json={"path": "mixed", "cloud": "anthropic"})
    mine = {j["job"]: j for j in client.get("/api/setup").json()["jobs"] if j["module"] == "setupprobe"}
    assert mine["read"]["provider"] == "anthropic" and mine["read"]["ready"] and mine["read"]["weight"] == "heavy"
    assert mine["sort"]["provider"] == "rules" and mine["sort"]["ready"]
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)                 # (a key in the environment would count)
    settings.update({"ai.anthropic_api_key": ""})                          # no key: it says what's missing
    mine = {j["job"]: j for j in client.get("/api/setup").json()["jobs"] if j["module"] == "setupprobe"}
    assert not mine["read"]["ready"] and "API key" in mine["read"]["reason"]


def test_the_recommendation_comes_from_this_macs_memory(client, monkeypatch):
    monkeypatch.setattr(resources, "device_advice", lambda local_min_gb=None: {"verdict": "mixed", "chip": "Apple M4", "ram_gb": 16,
                                                                               "disk_free_gb": 40, "notes": ["…"]})
    got = client.get("/api/setup").json()
    assert got["recommended"] == "mixed" and got["advice"]["chip"] == "Apple M4"


def test_an_app_already_in_use_skips_the_first_run_screens(client):
    # (the shared test app has settings saved, so it counts as in use)
    setup.mark_existing()
    assert setup.done() is True or settings.stored_here().get(setup.DONE) is not None


def test_a_fresh_app_is_new_until_setup_finishes(client, monkeypatch):
    monkeypatch.setattr(settings, "stored_here", lambda: {})
    saved = {}
    monkeypatch.setattr(settings, "update", lambda changes: saved.update(changes))
    setup.mark_existing()
    assert saved == {setup.DONE: False}
    monkeypatch.setattr(settings, "stored_here", lambda: {"core.your_name": "Sam"})
    saved.clear()
    setup.mark_existing()
    assert saved == {setup.DONE: True}                                     # it had settings of its own: an existing install
    monkeypatch.setattr(settings, "stored_here", lambda: {setup.DONE: False, "core.your_name": "Sam"})
    saved.clear()
    setup.mark_existing()
    assert saved == {}                                                     # already recorded: quitting mid-setup changes nothing


def test_finishing_is_remembered_and_reported(client):
    settings.update({setup.DONE: False})
    assert client.get("/api/app").json()["setup_done"] is False
    client.post("/api/setup/done")
    assert client.get("/api/app").json()["setup_done"] is True


def test_setup_can_be_run_again_without_touching_anything_else(client):
    settings.update({setup.DONE: True, "core.your_name": "Sam", "ai.path": "local"})
    assert client.post("/api/setup/reopen").json() == {"ok": True}
    assert client.get("/api/app").json()["setup_done"] is False            # the first-run screens show again
    after = settings.get_all()
    assert after["core.your_name"] == "Sam" and after["ai.path"] == "local"  # what was chosen stays chosen
    setup.mark_existing()
    assert setup.done() is False                                           # a restart doesn't count it as an old install
    client.post("/api/setup/done")
    assert client.get("/api/app").json()["setup_done"] is True
