"""The AI usage tally: tokens as the provider reported them, dollars at list price, local free, unknown models counted
but not priced, and warnings only for a big job."""
from types import SimpleNamespace

import pytest

from core.server import ai, db, settings, usage


@pytest.fixture(autouse=True)
def empty_tally():
    db.execute("DELETE FROM core_ai_usage")


def test_a_call_is_priced_from_the_tokens_the_provider_reported():
    usage.record("anthropic", "claude-opus-5-5", 1_000_000, 100_000, source="Note summaries")
    s = usage.summary()
    assert s["this_month"]["cost"] == pytest.approx(4.0 + 2.0)
    assert s["this_month"]["calls"] == 1 and s["this_month"]["tokens"] == 1_100_000
    assert s["by_source"][0]["name"] == "Note summaries"


def test_the_newest_models_match_their_own_prices_not_an_older_ones():
    assert usage.price("anthropic", "claude-opus-5-5") == (4.0, 20.0)
    assert usage.price("anthropic", "claude-sonnet-5-5") == (2.0, 10.0)
    assert usage.price("anthropic", "claude-haiku-5-5") == (0.10, 0.50)
    assert usage.price("anthropic", "claude-fable-5-1") == (10.0, 50.0)
    assert usage.price("gemini", "gemini-flash-latest") == (0.75, 3.75)


def test_a_local_model_is_counted_and_costs_nothing():
    usage.record("ollama", "qwen3:8b", 5000, 800, local=True)
    s = usage.summary()
    assert s["this_month"]["cost"] == 0 and s["this_month"]["calls"] == 1 and s["this_month"]["unpriced"] == 0
    assert s["by_model"][0]["local"] is True


def test_an_unknown_model_is_counted_but_flagged_unpriced():
    usage.record("custom", "mystery-1", 1000, 1000)
    s = usage.summary()
    assert s["this_month"]["cost"] == 0 and s["this_month"]["unpriced"] == 1 and s["by_model"][0]["priced"] is False


def test_a_cost_the_caller_worked_out_is_kept():
    usage.record("gemini", "gemini-3.8-flash", 100, 100, searches=3, cost=0.042, source="Researching people")
    assert usage.summary()["this_month"]["cost"] == pytest.approx(0.042)


def test_calls_through_ai_py_are_tallied_under_their_purpose(monkeypatch):
    values = {**ai.DEFAULTS, "provider": "openai", "openai_api_key": "k"}
    monkeypatch.setattr(ai.settings, "section", lambda namespace: values)
    reply = SimpleNamespace(json=lambda: {"choices": [{"message": {"content": "hello"}}],
                                          "usage": {"prompt_tokens": 2000, "completion_tokens": 500}})
    monkeypatch.setattr(ai, "_post", lambda *a, **k: reply)
    text, pid = ai.complete("hi", purpose="People overviews")
    assert (text, pid) == ("hello", "openai")
    row = usage.summary()["by_source"][0]
    assert row["name"] == "People overviews" and row["tokens"] == 2500 and row["cost"] > 0


def test_a_call_with_no_purpose_lands_under_other(monkeypatch):
    usage.record("openai", "gpt-5-mini", 10, 10)
    assert usage.summary()["by_source"][0]["name"] == usage.OTHER


def test_only_a_job_over_the_limit_is_big(monkeypatch):
    monkeypatch.setattr(usage.settings, "section", lambda namespace: {**ai.DEFAULTS, "warn_over": 5})
    assert not usage.is_big(4.99) and usage.is_big(5)
    monkeypatch.setattr(usage.settings, "section", lambda namespace: {**ai.DEFAULTS, "warn_over": 0})
    assert not usage.is_big(1000)


def test_the_limit_is_a_setting_with_a_default():
    assert "ai.warn_over" in settings.get_all() and settings.get_all()["ai.warn_over"] == 1
