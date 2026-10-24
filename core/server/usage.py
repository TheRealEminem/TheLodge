"""What AI has been asked to do, and about what it cost: a running tally for Settings, not a gate.

Every call through ai.py notes the tokens the provider reported (record). Dollars are those tokens at the list prices
in PRICES (as of PRICES_AS_OF), so they are an estimate; tokens are as reported. A job names itself with purpose("...")
so the tally can say what the spending went to. Local models are counted but cost nothing; a model with no known
price is counted and left out of the dollars (the tally says so).

Nothing here stops anything. The only interruption is for a job that would cost more than the `ai.warn_over`
setting (is_big): callers show their own estimate then, and stay quiet otherwise.
"""
import contextlib
import contextvars
import logging
from datetime import UTC, datetime, timedelta

from . import db, events, settings

log = logging.getLogger("core.usage")

PRICES_AS_OF = "2026-10-24"
# Dollars per 1M tokens: input, output (thinking included). The first key found inside the model's name wins, so
# the more specific names come first.
PRICES = {
    "anthropic": {"fable-5": (10.00, 50.00), "opus-5-5": (4.00, 20.00), "opus": (5.00, 25.00), "sonnet-5": (2.00, 10.00),
                  "sonnet": (3.00, 15.00), "haiku-5": (0.10, 0.50), "haiku": (1.00, 5.00)},
    "openai": {"gpt-5-mini": (0.25, 2.00), "gpt-5": (1.25, 10.00)},
    "deepseek": {"deepseek": (0.28, 0.42)},
    "gemini": {"flash-lite": (0.30, 2.50), "flash": (0.75, 3.75), "pro": (2.00, 12.00), "argon": (2.00, 10.00)},
}

_purpose: contextvars.ContextVar[str] = contextvars.ContextVar("ai_purpose", default="")
OTHER = "Other"

@contextlib.contextmanager
def purpose(name: str | None):
    """Calls made inside are tallied under this name. Nesting keeps the outermost name."""
    if not name or _purpose.get():
        yield
        return
    token = _purpose.set(name)
    try:
        yield
    finally:
        _purpose.reset(token)


def price(provider: str, model: str) -> tuple[float, float] | None:
    """(input, output) dollars per 1M tokens, or None if this model isn't one we know."""
    name = model.lower()
    for key, p in PRICES.get(provider, {}).items():
        if key in name:
            return p
    return None


def cost_of(provider: str, model: str, tokens_in: int, tokens_out: int) -> float | None:
    p = price(provider, model)
    if p is None:
        return None
    return round((tokens_in * p[0] + tokens_out * p[1]) / 1e6, 6)


def record(provider: str, model: str, tokens_in: int, tokens_out: int, *, local: bool = False, searches: int = 0,
           cost: float | None = None, source: str | None = None) -> None:
    """Note one call. cost: when the caller already worked it out (Gemini research, which also pays per search).
    Never raises: a tally that can't be written must not break the work."""
    try:
        if local:
            spent, priced = 0.0, True
        elif cost is not None:
            spent, priced = cost, True
        else:
            guess = cost_of(provider, model, tokens_in, tokens_out)
            spent, priced = (guess or 0.0), guess is not None
        db.execute(
            "INSERT INTO core_ai_usage (id, at, provider, model, source, tokens_in, tokens_out, searches, cost, local, priced) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (db.new_id(), db.now(), provider, model, source or _purpose.get() or OTHER, int(tokens_in or 0),
             int(tokens_out or 0), searches, spent, int(local), int(priced)))
        events.publish("core.usage.changed", {})
    except Exception:  # noqa: BLE001
        log.exception("couldn't record AI usage")


def warn_over() -> int:
    """Dollars above which a job is worth a warning; 0 turns warnings off."""
    return int(settings.section("ai")["warn_over"])


def is_big(estimate: float) -> bool:
    limit = warn_over()
    return limit > 0 and estimate >= limit


def _month_start(back: int = 0) -> str:
    d = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for _ in range(back):
        d = (d - timedelta(days=1)).replace(day=1)
    return d.isoformat().replace("+00:00", "Z")


def _total(since: str, until: str | None = None) -> dict:
    row = db.one("SELECT COALESCE(SUM(cost), 0) AS cost, COUNT(*) AS calls, COALESCE(SUM(tokens_in + tokens_out), 0) AS tokens, "
                 "COALESCE(SUM(1 - priced), 0) AS unpriced FROM core_ai_usage WHERE at >= ? AND at < ?",
                 (since, until or "9999")) or {}
    return {"cost": round(row.get("cost", 0), 4), "calls": row.get("calls", 0), "tokens": row.get("tokens", 0),
            "unpriced": row.get("unpriced", 0)}


def summary() -> dict:
    """For Settings → AI → Usage: this month and last, what it went to, which models, and day by day."""
    start = _month_start()
    this, last = _total(start), _total(_month_start(1), start)
    by_source = db.query("SELECT source AS name, COUNT(*) AS calls, SUM(cost) AS cost, SUM(tokens_in + tokens_out) AS tokens "
                         "FROM core_ai_usage WHERE at >= ? GROUP BY source ORDER BY cost DESC, calls DESC", (start,))
    by_model = db.query("SELECT provider, model, MAX(local) AS local, MIN(priced) AS priced, COUNT(*) AS calls, SUM(cost) AS cost, "
                        "SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out FROM core_ai_usage WHERE at >= ? "
                        "GROUP BY provider, model ORDER BY cost DESC, calls DESC", (start,))
    by_day = db.query("SELECT substr(at, 1, 10) AS day, SUM(cost) AS cost, COUNT(*) AS calls FROM core_ai_usage "
                      "WHERE at >= ? GROUP BY day ORDER BY day", (start,))
    return {"this_month": this, "last_month": last, "warn_over": warn_over(), "prices_as_of": PRICES_AS_OF,
            "by_source": [{**r, "cost": round(r["cost"], 4)} for r in by_source],
            "by_model": [{**r, "cost": round(r["cost"], 4), "local": bool(r["local"]), "priced": bool(r["priced"])} for r in by_model],
            "by_day": [{**r, "cost": round(r["cost"], 4)} for r in by_day]}
