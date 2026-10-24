"""Where AI runs: what "auto" means for each job once setup has chosen a path, what a small model on this Mac is trusted
with (basic mode), and that an install that was using Claude and Gemini keeps using them."""
import pytest
from crm_helpers import post_notes

from core.server import ai, resources, settings, setup
from modules.crm.server import ingest, roles
from modules.crm.server.extraction import BasicNotes, Extraction

NOTE = "Attendees: Zed Zulu, Priya Nair\nWe went over the depot pilot with enough words in it to be read properly.\nAction: Zed to send the fleet list."


@pytest.fixture
def mac(monkeypatch):
    """mac(ram): a Mac with this much memory, running a local model."""
    def make(ram):
        monkeypatch.setattr(resources, "snapshot", lambda: {"ram_total_gb": ram})
        monkeypatch.setattr(ai, "_ollama_tags", lambda c: [{"name": "qwen2.5:7b", "details": {"parameter_size": "7B"}}])
    return make


@pytest.fixture
def local(monkeypatch):
    """The path setup gives "On this Mac": everything on Ollama, every job on "auto"."""
    keys = ["ai.provider", "ai.heavy_provider", "ai.fallback", "ai.path"]
    before = {k: settings.get_all()[k] for k in keys}
    settings.update({"ai.provider": "ollama", "ai.heavy_provider": "auto", "ai.fallback": "none", "ai.path": "local",
                     "crm.extraction_provider": "auto", "crm.utility_provider": "auto"})
    yield
    settings.update(before)


def test_on_this_mac_sorting_and_columns_run_as_rules_and_reading_stays_with_the_model(local, mac):
    mac(16)
    assert roles.choice("utility") == "rules"
    for job in ("extraction", "profiles"):                          # "auto" is the app-wide provider, which setup made Ollama
        assert roles.choice(job) == "auto" and ai.describe(roles.choice(job))["provider"] == "ollama"
    settings.update({"crm.utility_provider": "ollama"})
    assert roles.choice("utility") == "ollama"                      # a model you name yourself is still used


def test_mixed_sends_only_the_careful_job_to_the_cloud(local, mac):
    mac(16)
    settings.update({"ai.path": "mixed", "ai.heavy_provider": "anthropic"})
    assert roles.choice("extraction") == "anthropic"
    assert ai.describe(roles.choice("profiles"))["provider"] == "ollama" and roles.choice("utility") == "rules"


def test_a_small_model_reads_the_notes_but_the_rules_find_the_people_and_a_person_looks_it_over(client, local, mac, fake_structured):
    mac(16)
    settings.update({"crm.webhook_auto_apply": True})
    fake_structured.reply = lambda prompt, system, schema: BasicNotes(
        summary="A walk through the depot pilot.", key_points=["Fleet list is next"], action_items=["Zed to send the fleet list"])
    job = post_notes(client, NOTE, title="Depot pilot")
    assert job["status"] == "review"                                 # even with auto-apply on
    assert job["extractor"].endswith("(basic)") and fake_structured.calls[0]["schema"] is BasicNotes
    proposal = job["proposal"]
    assert any(w.startswith(ingest.BASIC_WARNING_PREFIX) for w in proposal["warnings"]) and ingest.needs_review(proposal)
    names = {e["name"] for e in proposal["entities"]}
    assert {"Zed Zulu", "Priya Nair"} <= names                       # people found by rules
    assert "A walk through the depot pilot" in str(proposal["record"])
    assert not proposal["relationships"] or all(r["kind"] in ("attended", "discussed_in", "works_at") for r in proposal["relationships"])


def test_a_big_mac_trusts_a_local_model_with_the_whole_reading(client, local, mac, fake_structured):
    mac(32)
    fake_structured.reply = lambda prompt, system, schema: Extraction(doc_type="meeting_notes", title="Depot pilot", summary="Pilot.", entities=[])
    job = post_notes(client, NOTE, title="Depot pilot")
    assert fake_structured.calls[0]["schema"] is Extraction and not job["extractor"].endswith("(basic)")


def test_a_cloud_model_is_never_in_basic_mode(client, mac, fake_structured):
    mac(8)
    settings.update({"crm.extraction_provider": "anthropic"})
    fake_structured.reply = lambda prompt, system, schema: Extraction(doc_type="meeting_notes", title="Depot pilot", summary="Pilot.", entities=[])
    post_notes(client, NOTE, title="Depot pilot")
    assert fake_structured.calls[0]["schema"] is Extraction


# ── Keeping what people have ──────────────────────────────────────────

@pytest.fixture
def old_install(monkeypatch):
    """A settings store as an upgrade finds it: nothing about these jobs saved, keys for Claude and Gemini present."""
    stored = {}
    values = {"crm.providers_kept": False, "ai.anthropic_api_key": "sk-ant-key-1234567890", "ai.gemini_api_key": "gem-key-1234567890",
              "crm.extraction_provider": "auto", "crm.utility_provider": "auto"}
    monkeypatch.setattr(settings, "stored_here", lambda: stored)
    monkeypatch.setattr(settings, "get_all", lambda: {**values, **stored})
    monkeypatch.setattr(settings, "update", lambda changes: stored.update(changes))
    return stored, values


def test_an_install_that_was_using_claude_and_gemini_keeps_them(old_install, monkeypatch):
    stored, _ = old_install
    monkeypatch.setattr(setup, "done", lambda: True)                  # it had been in use before setup existed
    roles.keep_what_people_have()
    assert stored == {"crm.extraction_provider": "anthropic", "crm.utility_provider": "gemini", "crm.providers_kept": True}
    stored["crm.extraction_provider"] = "ollama"                      # later choices stand: it only ever runs once
    roles.keep_what_people_have()
    assert stored["crm.extraction_provider"] == "ollama"


def test_a_job_you_chose_before_is_left_alone_and_a_missing_key_pins_nothing(old_install, monkeypatch):
    stored, values = old_install
    stored["crm.extraction_provider"] = "openai"
    values["ai.gemini_api_key"] = ""
    monkeypatch.setattr(setup, "done", lambda: True)
    roles.keep_what_people_have()
    assert stored == {"crm.extraction_provider": "openai", "crm.providers_kept": True}


def test_a_new_install_follows_setup_instead(old_install, monkeypatch):
    stored, _ = old_install
    monkeypatch.setattr(setup, "done", lambda: False)                 # first run: setup hasn't happened yet
    roles.keep_what_people_have()
    assert stored == {"crm.providers_kept": True}
