"""What AI calls cost and the usage log: the price table's arithmetic, unknown prices staying unknown, the totals
Settings shows, and which module and job each call is put down to. Nothing here reaches a real model."""
from datetime import datetime, timedelta, timezone

import pytest

from core.server import ai, db, jobs, pricing

UTC = timezone.utc
OCT_21 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def empty_log():
    db.execute("DELETE FROM core_ai_usage")


def rows() -> list[dict]:
    return db.query("SELECT * FROM core_ai_usage ORDER BY at")


# ── Prices ─────────────────────────────────────────────────────────────

def test_a_call_costs_its_input_and_output_at_the_published_price():
    assert pricing.cost("anthropic", "claude-opus-5-5", 1_000_000, 1_000_000) == pytest.approx(24.00)
    assert pricing.cost("openai", "gpt-5-mini", 10_000, 2_000) == pytest.approx(0.0025 + 0.004)
    assert pricing.cost("anthropic", "claude-sonnet-5-5", 2_000, 400) == pytest.approx((2_000 * 2 + 400 * 10) / 1e6)


def test_tokens_read_from_the_cache_cost_the_cache_price():
    # 1M in, 800K of them from the cache: 200K at $0.25 and 800K at $0.025, plus 0 out.
    assert pricing.cost("openai", "gpt-5-mini", 1_000_000, 0, cached=800_000) == pytest.approx(0.05 + 0.02)


def test_a_dated_snapshot_is_priced_as_its_model():
    assert pricing.lookup("openai", "gpt-5-mini-2025-08-07") == pricing.OPENAI["gpt-5-mini"]
    assert pricing.lookup("anthropic", "claude-haiku-4-5-20251001") == pricing.ANTHROPIC["claude-haiku-4-5"]
    assert pricing.lookup("gemini", "models/gemini-2.5-flash") == pricing.GEMINI["gemini-2.5-flash"]
    assert pricing.lookup("openai", "gpt-5") != pricing.lookup("openai", "gpt-5-mini")  # never a shorter name's price


def test_a_bigger_prompt_can_cost_more_per_token():
    small = pricing.cost("anthropic", "claude-haiku-5-5", 100_000, 1_000)
    big = pricing.cost("anthropic", "claude-haiku-5-5", 100_001, 1_000)
    assert small == pytest.approx((100_000 * 0.10 + 1_000 * 0.50) / 1e6)
    assert big == pytest.approx((100_001 * 0.50 + 1_000 * 2.50) / 1e6)
    assert pricing.cost("gemini", "gemini-2.5-pro", 300_000, 0) == pytest.approx(300_000 * 2.50 / 1e6)


def test_a_price_that_changes_on_a_known_day_is_used_from_that_day():
    before = datetime(2026, 12, 31, 23, 0, tzinfo=UTC)
    after = datetime(2027, 1, 1, 0, 1, tzinfo=UTC)
    assert pricing.cost("gemini", "gemini-3.8-flash", 1_000_000, 0, at=before) == pytest.approx(0.75)
    assert pricing.cost("gemini", "gemini-3.8-flash", 1_000_000, 0, at=after) == pytest.approx(1.50)


def test_deepseek_costs_double_in_its_weekday_peak_hours():
    monday_2am = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
    monday_5am = datetime(2026, 10, 19, 5, 0, tzinfo=UTC)
    saturday_2am = datetime(2026, 10, 24, 2, 0, tzinfo=UTC)
    peak, quiet, weekend = (pricing.cost("deepseek", "deepseek-flash", 1_000_000, 1_000_000, at=t)
                            for t in (monday_2am, monday_5am, saturday_2am))
    assert peak == pytest.approx(0.30 + 1.20) and quiet == pytest.approx(0.15 + 0.60) and weekend == quiet


# ── Unknown prices ─────────────────────────────────────────────────────

@pytest.mark.parametrize("provider, model", [
    ("openai", "gpt-99"),
    ("gemini", "gemini-flash-latest"),     # an alias: what it points to isn't published
    ("deepseek", "deepseek-chat"),         # retired, so no longer priced
    ("custom", "anything"),                # a server somewhere: nobody publishes its price here
])
def test_a_model_without_a_published_price_costs_unknown_not_nothing(provider, model):
    assert pricing.lookup(provider, model) is None
    assert pricing.cost(provider, model, 1000, 100) is None


def test_cache_reads_on_a_model_without_a_published_cache_price_are_unknown():
    assert pricing.cost("anthropic", "claude-opus-5", 1000, 100) is not None
    assert pricing.cost("anthropic", "claude-opus-5", 1000, 100, cached=500) is None


def test_missing_token_counts_make_the_cost_unknown():
    assert pricing.cost("anthropic", "claude-opus-5-5", None, 100) is None
    meter = pricing.Meter("openai", "gpt-5-mini")
    meter.add(1000, None)
    assert meter.cost(OCT_21) is None


def test_local_models_cost_nothing_whatever_the_model():
    meter = pricing.Meter("ollama", "qwen3:8b", free=True)
    meter.add(5000, 800)
    assert meter.cost(OCT_21) == 0.0
    assert ai.is_free("ollama", {"ollama_url": "http://192.168.1.9:11434"})
    assert ai.is_free("custom", {"custom_base_url": "http://localhost:1234/v1"})
    assert not ai.is_free("custom", {"custom_base_url": "https://openrouter.ai/api/v1"})
    assert not ai.is_free("anthropic", {})


def test_a_reply_that_names_a_model_off_the_table_is_priced_as_the_model_asked_for():
    meter = pricing.Meter("deepseek", "deepseek-flash")
    meter.add(1_000_000, 0, model="deepseek-v4.1-flash-1017")     # what DeepSeek says now serves "deepseek-flash"
    assert meter.cost(datetime(2026, 10, 24, 12, tzinfo=UTC)) == pytest.approx(0.15)


# ── The log ────────────────────────────────────────────────────────────

def test_an_unknown_price_is_logged_as_unknown_and_left_out_of_the_total():
    meter = pricing.Meter("openai", "gpt-99", asker=("probe", "think"))
    meter.add(1000, 200)
    meter.record("complete")
    [row] = rows()
    assert row["cost"] is None and row["input_tokens"] == 1000 and row["output_tokens"] == 200 and not row["failed"]
    month = pricing.summary()["month"]
    assert (month["calls"], month["unknown"], month["cost"]) == (1, 1, 0)


def test_a_failed_call_is_logged_without_a_cost(cfg, monkeypatch):
    cfg(provider="gemini", gemini_api_key="g")
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(ai.httpx.ConnectError("no route")))
    with pytest.raises(ai.AIError):
        ai.complete("hi")
    [row] = rows()
    assert row["failed"] == 1 and row["cost"] is None and row["input_tokens"] is None and "no route" in row["error"]
    assert (row["provider"], row["model"], row["call"]) == ("gemini", "gemini-flash-latest", "complete")
    month = pricing.summary()["month"]
    assert (month["calls"], month["failed"], month["unknown"], month["cost"]) == (1, 1, 0, 0)  # nothing spent, nothing unknown


def test_a_failed_answer_that_was_billed_keeps_its_cost():
    meter = pricing.Meter("anthropic", "claude-opus-5-5")
    meter.add(1000, 32000)                       # ran out of output space: Claude still billed every token
    meter.record("structured", error="Claude ran out of output space before it finished")
    [row] = rows()
    assert row["failed"] == 1 and row["cost"] == pytest.approx((1000 * 4 + 32000 * 20) / 1e6)


def test_bookkeeping_never_fails_the_call(cfg, monkeypatch):
    cfg(provider="openai", openai_api_key="k")
    monkeypatch.setattr(pricing.db, "execute", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("disk full")))
    monkeypatch.setattr(ai.httpx, "post", lambda url, **kw: ai.httpx.Response(
        200, json={"choices": [{"message": {"content": "Hi"}}]}, request=ai.httpx.Request("POST", url)))
    assert ai.complete("hi") == ("Hi", "openai")


def test_a_call_is_put_down_to_the_module_and_job_that_asked(fake_structured):
    from pydantic import BaseModel

    class Answer(BaseModel):
        text: str

    fake_structured.reply = Answer(text="ok")
    jobs.register("probe", "think", lambda job: ai.structured("x", "s", Answer))
    jobs.enqueue("probe", "think", "t1")
    jobs.drain()
    ai.structured("outside", "s", Answer)        # not in a job
    by_job, outside = rows()
    assert (by_job["module"], by_job["job"], by_job["provider"], by_job["model"]) == ("probe", "think", "anthropic", "claude-opus-5-5")
    assert by_job["cost"] == pytest.approx((2000 * 4 + 400 * 20) / 1e6)       # the fake's tokens, at Opus 5.5's price
    assert (outside["module"], outside["job"]) == ("", "")


def test_the_test_button_is_put_down_to_settings(cfg, monkeypatch):
    cfg(gemini_api_key="g")
    monkeypatch.setattr(ai.httpx, "post", lambda url, **kw: ai.httpx.Response(200, json={
        "model": "gemini-3.8-flash", "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50},
        "choices": [{"message": {"content": '{"answer": "OK", "number": 7}'}, "finish_reason": "stop"}]},
        request=ai.httpx.Request("POST", url)))
    ai.test("gemini")
    [row] = rows()
    assert (row["module"], row["job"], row["model"]) == ("core", "test", "gemini-3.8-flash")
    assert row["cost"] == pytest.approx((40 * 0.75 + 10 * 3.75) / 1e6)


# ── Totals for Settings ────────────────────────────────────────────────

def log(at: datetime, provider="anthropic", model="claude-opus-5-5", module="probe", cost=0.10, failed=0, tokens=1000):
    db.execute("INSERT INTO core_ai_usage (id, at, module, job, call, provider, model, input_tokens, cached_tokens, "
               "output_tokens, cost, failed) VALUES (?, ?, ?, 'think', 'structured', ?, ?, ?, 0, ?, ?, ?)",
               (db.new_id(), pricing._stamp(at), module, provider, model, tokens, tokens and tokens // 10, cost, failed))


def test_totals_for_this_month_and_the_last_30_days_by_provider_and_module():
    now = datetime(2026, 10, 21, 12, 0).astimezone()            # this machine's time zone, as in the app
    log(now - timedelta(hours=1), cost=0.50)
    log(now - timedelta(days=2), provider="gemini", model="gemini-3.8-flash", module="core", cost=0.02)
    log(now - timedelta(days=3), provider="openai", model="gpt-99", cost=None)       # unknown price
    log(now - timedelta(days=4), provider="ollama", model="qwen3:8b", cost=0.0)
    log(now - timedelta(days=25), cost=1.00)                                         # September: 30 days, not this month
    log(now - timedelta(days=40), cost=9.00)                                         # older than both

    got = pricing.summary(now)
    month, days30 = got["month"], got["last_30_days"]
    assert (month["calls"], month["cost"], month["unknown"]) == (4, pytest.approx(0.52), 1)
    assert (days30["calls"], days30["cost"], days30["unknown"]) == (5, pytest.approx(1.52), 1)
    providers = {p["id"]: (p["calls"], p["cost"], p["unknown"]) for p in days30["by_provider"]}
    assert providers == {"anthropic": (2, pytest.approx(1.50), 0), "gemini": (1, pytest.approx(0.02), 0),
                         "openai": (1, 0, 1), "ollama": (1, 0, 0)}
    assert [p["id"] for p in days30["by_provider"]][:2] == ["anthropic", "gemini"]   # the most spent first
    assert {m["id"]: m["calls"] for m in days30["by_module"]} == {"probe": 4, "core": 1}
    assert [c["cost"] for c in got["recent"][:3]] == [0.50, 0.02, None] and got["recent"][2]["unknown"] is True


def test_the_usage_api_names_providers_and_modules(client):
    log(datetime.now(UTC) - timedelta(minutes=5), module="core", provider="gemini", model="gemini-3.8-flash")
    log(datetime.now(UTC) - timedelta(minutes=1), module="probe")
    log(datetime.now(UTC), module="", provider="custom", model="m", cost=None)
    got = client.get("/api/ai/usage").json()
    labels = {m["id"]: m["label"] for m in got["last_30_days"]["by_module"]}
    assert labels == {"probe": "Probe", "core": "Settings", "": "Outside a job"}
    assert {p["id"]: p["label"] for p in got["last_30_days"]["by_provider"]}["gemini"] == "Google Gemini"
    first = got["recent"][0]
    assert (first["provider_label"], first["module_label"], first["unknown"]) == ("OpenAI-compatible", "Outside a job", True)
    assert got["prices_checked"] == pricing.CHECKED and got["month"]["start"].endswith("Z")


@pytest.fixture
def cfg(monkeypatch):
    values = dict(ai.DEFAULTS)

    def use(**overrides):
        values.update(overrides)
        return values

    monkeypatch.setattr(ai.settings, "section", lambda namespace: values)
    return use
