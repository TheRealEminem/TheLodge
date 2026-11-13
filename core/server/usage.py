"""What AI has been asked to do, and about what it cost: a running tally for Settings, not a gate.

There is one tally: core_ai_usage, written by pricing.write(). Every call through ai.py is written there as it
finishes (ai.attempt, with the tokens each provider reported, priced by pricing.py's tables), and so is anything that
pays for AI outside ai.py, which says so with record() (Gemini research, which also pays per search). A job names
itself with purpose("...") so the tally can say what the spending went to. Local models are counted but cost nothing;
a model with no known price is counted and left out of the dollars (the tally says so).

Nothing here stops anything. The only interruption is for a job that would cost more than the `ai.warn_over`
setting (is_big): callers show their own estimate then, and stay quiet otherwise.

summary() is the month-by-month view Settings → AI → Usage shows. pricing.summary() is the other view of the same rows:
the last 30 days by provider and module, and the latest calls (AIUsage.tsx). GET /api/ai/usage returns both (ai.usage_report).
"""
import logging
from datetime import UTC, datetime, timedelta

from . import db, events, pricing, settings
from .pricing import OTHER, purpose

__all__ = ["OTHER", "purpose", "price", "cost_of", "record", "warn_over", "is_big", "summary", "PRICES_AS_OF"]

log = logging.getLogger("core.usage")

PRICES_AS_OF = pricing.CHECKED


# For estimating a job before it runs: an alias the tally can't price (the reply of a real call names the model it
# resolved to, which can) is estimated at what it points to now.
ESTIMATE_AS = {("gemini", "gemini-flash-latest"): "gemini-3.8-flash"}


def price(provider: str, model: str) -> tuple[float, float] | None:
    """(input, output) dollars per 1M tokens at the base rate, or None if this model isn't one pricing.py knows."""
    found = pricing.lookup(provider, ESTIMATE_AS.get((provider, model), model))
    return (found.input, found.output) if found else None


def cost_of(provider: str, model: str, tokens_in: int, tokens_out: int) -> float | None:
    spent = pricing.cost(provider, model, tokens_in, tokens_out)
    return None if spent is None else round(spent, 6)


def record(provider: str, model: str, tokens_in: int, tokens_out: int, *, local: bool = False, searches: int = 0,
           cost: float | None = None, source: str | None = None) -> None:
    """Note one call made outside ai.py. cost: when the caller already worked it out (Gemini research, which also pays
    per search). Never raises: a tally that can't be written must not break the work."""
    spent = 0.0 if local else cost if cost is not None else cost_of(provider, model, tokens_in, tokens_out)
    pricing.write(provider=provider, model=model, input_tokens=int(tokens_in or 0), output_tokens=int(tokens_out or 0),
                  cost=spent, local=local, searches=searches, source=source)
    events.publish("core.usage.changed", {})


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


# A call Lockdown stopped never left this computer, so it isn't a call the tally counts here.
_COUNTED = f"NOT ({pricing.STOPPED})"


def _total(since: str, until: str | None = None) -> dict:
    row = db.one("SELECT COALESCE(SUM(cost), 0) AS cost, COUNT(*) AS calls, "
                 "COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0) AS tokens, "
                 f"COALESCE(SUM(CASE WHEN {pricing.UNKNOWN} THEN 1 ELSE 0 END), 0) AS unpriced "
                 f"FROM core_ai_usage WHERE at >= ? AND at < ? AND {_COUNTED}", (since, until or "9999")) or {}
    return {"cost": round(row.get("cost", 0), 4), "calls": row.get("calls", 0), "tokens": row.get("tokens", 0),
            "unpriced": row.get("unpriced", 0)}


def summary() -> dict:
    """For Settings → AI → Usage: this month and last, what it went to, which models, and day by day."""
    start = _month_start()
    this, last = _total(start), _total(_month_start(1), start)
    by_source = db.query("SELECT source AS name, COUNT(*) AS calls, COALESCE(SUM(cost), 0) AS cost, "
                         "SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) AS tokens FROM core_ai_usage "
                         f"WHERE at >= ? AND {_COUNTED} GROUP BY source ORDER BY cost DESC, calls DESC", (start,))
    by_model = db.query("SELECT provider, model, MAX(local) AS local, "
                        f"MIN(CASE WHEN {pricing.UNKNOWN} THEN 0 ELSE 1 END) AS priced, COUNT(*) AS calls, "
                        "COALESCE(SUM(cost), 0) AS cost, SUM(COALESCE(input_tokens, 0)) AS tokens_in, "
                        "SUM(COALESCE(output_tokens, 0)) AS tokens_out FROM core_ai_usage "
                        f"WHERE at >= ? AND {_COUNTED} GROUP BY provider, model ORDER BY cost DESC, calls DESC", (start,))
    by_day = db.query("SELECT substr(at, 1, 10) AS day, COALESCE(SUM(cost), 0) AS cost, COUNT(*) AS calls FROM core_ai_usage "
                      f"WHERE at >= ? AND {_COUNTED} GROUP BY day ORDER BY day", (start,))
    return {"this_month": this, "last_month": last, "warn_over": warn_over(), "prices_as_of": PRICES_AS_OF,
            "by_source": [{**r, "cost": round(r["cost"], 4)} for r in by_source],
            "by_model": [{**r, "cost": round(r["cost"], 4), "local": bool(r["local"]), "priced": bool(r["priced"])} for r in by_model],
            "by_day": [{**r, "cost": round(r["cost"], 4)} for r in by_day]}
