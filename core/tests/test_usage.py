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


# ── One table, whichever way an older copy of the app made it ───────────

FAMILY_SHAPE = """CREATE TABLE core_ai_usage (id TEXT PRIMARY KEY, at TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
    source TEXT NOT NULL, tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL, searches INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL, local INTEGER NOT NULL, priced INTEGER NOT NULL);
    CREATE INDEX core_ai_usage_at ON core_ai_usage(at);"""
PRICING_SHAPE = """CREATE TABLE core_ai_usage (id TEXT PRIMARY KEY, at TEXT NOT NULL, module TEXT NOT NULL, job TEXT NOT NULL,
    call TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER, cached_tokens INTEGER,
    output_tokens INTEGER, cost REAL, failed INTEGER NOT NULL DEFAULT 0, error TEXT);
    CREATE INDEX core_ai_usage_at ON core_ai_usage(at);"""


def _columns(conn):
    return [r[1] for r in conn.execute("PRAGMA table_info(core_ai_usage)")]


def test_a_table_made_by_the_counting_apps_becomes_the_one_table():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.executescript(FAMILY_SHAPE)
    conn.executemany("INSERT INTO core_ai_usage VALUES (?, '2026-10-01T00:00:00.000Z', ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        ("a", "anthropic", "claude-opus-5-5", "Note summaries", 1000, 200, 0, 0.008, 0, 1),
        ("b", "custom", "mystery-1", "Other", 10, 10, 0, 0.0, 0, 0),
        ("c", "ollama", "qwen3:8b", "Other", 50, 5, 0, 0.0, 1, 1)])
    db._one_ai_tally(conn)
    rows = {r[0]: r for r in conn.execute("SELECT id, input_tokens, output_tokens, cost, source, local, failed FROM core_ai_usage")}
    assert rows["a"][1:] == (1000, 200, 0.008, "Note summaries", 0, 0)
    assert rows["b"][3] is None                       # it was never priced: the cost is not known, not nothing
    assert rows["c"][3] == 0 and rows["c"][5] == 1    # a local model: free, and here
    assert {"module", "job", "call", "cached_tokens", "error", "source", "searches", "local"} <= set(_columns(conn))
    assert conn.execute("SELECT tokens_in, tokens_out FROM core_ai_usage WHERE id = 'a'").fetchone() == (1000, 200)


def test_a_table_made_by_the_logging_app_gains_what_the_other_kind_has():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.executescript(PRICING_SHAPE)
    conn.execute("INSERT INTO core_ai_usage VALUES ('a', '2026-10-01T00:00:00.000Z', 'inbox', 'extract', 'structured', "
                 "'ollama', 'qwen3:8b', 10, 0, 5, 0.0, 0, NULL)")
    db._one_ai_tally(conn)
    assert {"source", "searches", "local"} <= set(_columns(conn))
    assert conn.execute("SELECT module, job, source, local, tokens_in, tokens_out FROM core_ai_usage").fetchone() == ("inbox", "extract", "", 1, 10, 5)


@pytest.mark.parametrize("shape", [FAMILY_SHAPE, PRICING_SHAPE])
def test_a_step_cut_off_before_its_version_was_noted_can_run_again(shape):
    """The step's changes are committed before db.migrate notes the version, so a stop in between repeats it."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.executescript(shape)
    db._one_ai_tally(conn)
    db._one_ai_tally(conn)
    assert {"input_tokens", "source", "local"} <= set(_columns(conn))
    conn.execute("SELECT tokens_in, tokens_out, priced FROM core_ai_usage")


@pytest.mark.parametrize("shape", [FAMILY_SHAPE, PRICING_SHAPE])
def test_the_version_before_can_still_read_the_table_after_go_back(shape):
    """Go back runs the older code on this table: its reports read tokens_in, tokens_out and priced."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.executescript(shape)
    db._one_ai_tally(conn)
    conn.execute("INSERT INTO core_ai_usage (id, at, module, job, call, provider, model, input_tokens, output_tokens, cost) "
                 "VALUES ('known', 't', '', '', 'complete', 'openai', 'm', 10, 5, 0.1), "
                 "('unknown', 't', '', '', 'complete', 'custom', 'm', 10, 5, NULL)")
    assert conn.execute("SELECT id, tokens_in, tokens_out, priced FROM core_ai_usage ORDER BY id").fetchall() == [
        ("known", 10, 5, 1), ("unknown", 10, 5, 0)]


def test_the_two_views_read_the_same_rows(monkeypatch):
    values = {**ai.DEFAULTS, "provider": "openai", "openai_api_key": "k"}
    monkeypatch.setattr(ai.settings, "section", lambda namespace: values)
    reply = SimpleNamespace(json=lambda: {"choices": [{"message": {"content": "hello"}}],
                                          "usage": {"prompt_tokens": 2000, "completion_tokens": 500}})
    monkeypatch.setattr(ai, "_post", lambda *a, **k: reply)
    ai.complete("hi", purpose="People overviews")
    usage.record("gemini", "gemini-3.8-flash", 100, 100, searches=3, cost=0.042, source="Researching people")
    both = ai.usage_report()
    assert both["this_month"]["calls"] == 2 == both["month"]["calls"] == both["last_30_days"]["calls"]
    assert {r["name"] for r in both["by_source"]} == {"People overviews", "Researching people"}
    assert [r["label"] for r in both["last_30_days"]["by_provider"] if r["id"] == "gemini"] == ["Google Gemini"]
