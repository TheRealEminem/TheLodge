"""What AI calls cost, and a record of every one: the numbers behind Settings → AI's usage.

Prices are dollars per million tokens, as each provider publishes them (CHECKED says when; each table names its
source). Thinking is billed as output everywhere. A model that isn't in its provider's table has an *unknown*
cost, never 0: a guess would make the total look smaller than the bill. Models that run on your own machines
(Ollama, or an OpenAI-compatible server on localhost) cost nothing.

ai.attempt() is the one place calls are counted. It gives each provider's attempt a Meter; the adapter names the
model and reports the tokens of every request the provider answered, and the attempt is written to
core_ai_usage whether it worked or not: when, which module's job asked, provider, model, tokens, cost, and the
error if it failed. The cost is worked out when the call is made, so a later price change doesn't rewrite what
was spent. A failed attempt that got no answer has no tokens and no cost; one that got an answer and failed on
it anyway (a refusal, running out of output, the wrong shape) was billed, so it's counted. A call Lockdown stopped
(lockdown.py) never left the Mac: it's logged as *stopped*, failed with Lockdown's reason, at a cost of 0, and
counted apart from failures.
"""
import contextlib
import contextvars
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import db, jobs, lockdown

log = logging.getLogger("core.ai")

CHECKED = "2026-10-21"   # when the tables below were last read from the providers' pages


@dataclass(frozen=True)
class Price:
    """Dollars per million tokens. cached: input read from the provider's cache (None: not published, so a call
    that read from it has an unknown cost). above: (prompt tokens, the price for a bigger prompt). then: (UTC day,
    the price from that day on). peak: DeepSeek's price in its busy hours."""
    input: float
    output: float
    cached: float | None = None
    above: tuple[int, "Price"] | None = None
    then: tuple[str, "Price"] | None = None
    peak: "Price | None" = None


# The claude-api skill's model table (cached 2026-10-06) and its model notes for cache reads.
ANTHROPIC = {
    "claude-fable-5-1": Price(10.00, 50.00, cached=0.25),
    "claude-mythos-5-1": Price(10.00, 50.00, cached=0.25),
    "claude-fable-5": Price(10.00, 50.00, cached=1.00),
    "claude-mythos-5": Price(10.00, 50.00, cached=1.00),
    "claude-opus-5-5": Price(4.00, 20.00, cached=0.20),
    "claude-opus-5": Price(5.00, 25.00),
    "claude-opus-4-8": Price(5.00, 25.00),
    "claude-opus-4-7": Price(5.00, 25.00),
    "claude-opus-4-6": Price(5.00, 25.00),
    "claude-sonnet-5-5": Price(2.00, 10.00, cached=0.20),
    "claude-sonnet-5": Price(2.00, 10.00),
    "claude-sonnet-4-6": Price(3.00, 15.00),
    "claude-haiku-5-5": Price(0.10, 0.50, above=(100_000, Price(0.50, 2.50))),
    "claude-haiku-4-5": Price(1.00, 5.00),
}

# developers.openai.com/api/docs/pricing, Standard tier. Long context is over 272K input tokens.
# GPT-5.6 Sol's price is promotional "at least through November 21, 2026".
_LONG = 272_000
OPENAI = {
    "gpt-6-astra": Price(10.00, 50.00, 1.00, above=(_LONG, Price(20.00, 75.00, 2.00))),
    "gpt-6.1-sol": Price(2.00, 10.00, 0.10, above=(_LONG, Price(4.00, 15.00, 0.20))),
    "gpt-6-sol": Price(2.00, 10.00, 0.20, above=(_LONG, Price(4.00, 15.00, 0.40))),
    "gpt-6-luna": Price(0.10, 0.50, 0.01, above=(_LONG, Price(0.20, 0.75, 0.02))),
    "gpt-5.6-sol": Price(4.00, 20.00, 0.40, above=(_LONG, Price(8.00, 30.00, 0.80))),
    "gpt-5.6-terra": Price(2.00, 12.00, 0.20, above=(_LONG, Price(4.00, 18.00, 0.40))),
    "gpt-5.6-luna": Price(0.20, 1.20, 0.02, above=(_LONG, Price(0.40, 1.80, 0.04))),
    "gpt-5.5": Price(5.00, 30.00, 0.50, above=(_LONG, Price(10.00, 45.00, 1.00))),
    "gpt-5.5-pro": Price(30.00, 180.00, above=(_LONG, Price(60.00, 270.00))),
    "gpt-5.4": Price(2.50, 15.00, 0.25, above=(_LONG, Price(5.00, 22.50, 0.50))),
    "gpt-5.4-pro": Price(30.00, 180.00, above=(_LONG, Price(60.00, 270.00))),
    "gpt-5.4-mini": Price(0.75, 4.50, 0.075),
    "gpt-5.4-nano": Price(0.20, 1.25, 0.02),
    "gpt-5.2": Price(1.75, 14.00, 0.175),
    "gpt-5.2-pro": Price(21.00, 168.00),
    "gpt-5.1": Price(1.25, 10.00, 0.125),
    "gpt-5": Price(1.25, 10.00, 0.125),
    "gpt-5-mini": Price(0.25, 2.00, 0.025),
    "gpt-5-nano": Price(0.05, 0.40, 0.005),
    "gpt-5-pro": Price(15.00, 120.00),
    "gpt-4.1": Price(2.00, 8.00, 0.50),
    "gpt-4.1-mini": Price(0.40, 1.60, 0.10),
    "gpt-4.1-nano": Price(0.10, 0.40, 0.025),
    "gpt-4o": Price(2.50, 10.00, 1.25),
    "gpt-4o-mini": Price(0.15, 0.60, 0.075),
    "o3": Price(2.00, 8.00, 0.50),
    "o4-mini": Price(1.10, 4.40, 0.275),
}

# ai.google.dev/gemini-api/docs/pricing (updated 2026-10-19), paid tier, text. The -latest aliases aren't priced:
# the page doesn't say what they point to, so a call is priced by the model the reply names.
_FLASH_38 = Price(0.75, 3.75, 0.075, then=("2027-01-01", Price(1.50, 7.50, 0.15)))
GEMINI = {
    "gemini-4-argon": Price(2.00, 10.00, 0.10, then=("2026-12-01", Price(4.00, 20.00, 0.20))),
    "gemini-3.8-flash": _FLASH_38,
    "gemini-3.6-flash": _FLASH_38,
    "gemini-3.5-flash-lite": Price(0.30, 2.50, 0.03),
    "gemini-3.1-flash-lite": Price(0.25, 1.50, 0.025),
    "gemini-3.1-pro-preview": Price(2.00, 12.00, 0.20, above=(200_000, Price(4.00, 18.00, 0.40))),
    "gemini-3-flash-preview": Price(0.50, 3.00, 0.05),
    "gemini-2.5-pro": Price(1.25, 10.00, 0.125, above=(200_000, Price(2.50, 15.00, 0.25))),
    "gemini-2.5-flash": Price(0.30, 2.50, 0.03),
    "gemini-2.5-flash-lite": Price(0.10, 0.40, 0.01),
}

# api-docs.deepseek.com/quick_start/pricing. The old deepseek-v4-flash names are billed at Flash's price;
# deepseek-chat and deepseek-reasoner were retired on 2026-07-24 and have no price.
_DS_FLASH = Price(0.15, 0.60, 0.003, peak=Price(0.30, 1.20, 0.006))
DEEPSEEK = {
    "deepseek-flash": _DS_FLASH,
    "deepseek-v4-flash": _DS_FLASH,
    "deepseek-v4-flash-vision-exp": _DS_FLASH,
    "deepseek-v4-pro": Price(0.66, 1.98, 0.022, peak=Price(1.32, 3.96, 0.044)),
}

PRICES = {"anthropic": ANTHROPIC, "openai": OPENAI, "gemini": GEMINI, "deepseek": DEEPSEEK}

_SNAPSHOT = re.compile(r"-(\d{4}-\d{2}-\d{2}|\d{8})$")   # gpt-5-mini-2025-08-07, claude-haiku-4-5-20251001


def lookup(provider: str, model: str | None) -> Price | None:
    """The published price of a model, or None. A dated snapshot is priced as its model."""
    table = PRICES.get(provider, {})
    name = (model or "").removeprefix("models/")
    return table.get(name) or table.get(_SNAPSHOT.sub("", name))


def _deepseek_busy(at: datetime) -> bool:
    """DeepSeek's peak hours: 01:00-04:00 and 06:00-10:00 UTC on weekdays. Chinese public holidays are off-peak
    too; they aren't known here, so a call on one is counted at the peak price."""
    t = at.astimezone(timezone.utc)
    return t.weekday() < 5 and (1 <= t.hour < 4 or 6 <= t.hour < 10)


def rate(price: Price, at: datetime, prompt_tokens: int) -> Price:
    """The price that applies to one request: on that day, at that hour, for a prompt that size."""
    if price.then and at.astimezone(timezone.utc).date().isoformat() >= price.then[0]:
        return rate(price.then[1], at, prompt_tokens)
    if price.peak and _deepseek_busy(at):
        return rate(price.peak, at, prompt_tokens)
    if price.above and prompt_tokens > price.above[0]:
        return price.above[1]
    return price


def cost(provider: str, model: str, input_tokens: int | None, output_tokens: int | None, cached: int = 0,
         at: datetime | None = None) -> float | None:
    """Dollars for one request, or None when the price or the tokens aren't known. input_tokens includes the
    cached ones."""
    price = lookup(provider, model)
    if price is None or input_tokens is None or output_tokens is None:
        return None
    r = rate(price, at or datetime.now(timezone.utc), input_tokens)
    if cached and r.cached is None:
        return None
    return ((input_tokens - cached) * r.input + cached * (r.cached or 0) + output_tokens * r.output) / 1_000_000


# ── Counting a call ────────────────────────────────────────────────────

_purpose: contextvars.ContextVar[str] = contextvars.ContextVar("ai_purpose", default="")
OTHER = "Other"


@contextlib.contextmanager
def purpose(name: str | None):
    """Calls made inside are tallied under this name ("Note summaries"), so the usage panel can say what the spending
    went to. Nesting keeps the outermost name."""
    if not name or _purpose.get():
        yield
        return
    token = _purpose.set(name)
    try:
        yield
    finally:
        _purpose.reset(token)


def write(*, provider: str, model: str, call: str = "complete", input_tokens: int | None = None,
          cached_tokens: int | None = None, output_tokens: int | None = None, cost: float | None = None,
          error: str | None = None, local: bool = False, searches: int = 0, source: str | None = None,
          asker: tuple[str, str] | None = None, when: datetime | None = None) -> None:
    """The one row every counted AI call becomes (core_ai_usage). cost: dollars, None when it isn't known. Never
    raises: a call doesn't fail over its own bookkeeping."""
    try:
        job = jobs.current()
        module, kind = asker or ((job.module, job.kind) if job else ("", ""))
        db.execute(
            "INSERT INTO core_ai_usage (id, at, module, job, call, provider, model, input_tokens, cached_tokens, "
            "output_tokens, cost, failed, error, source, searches, local) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (db.new_id(), _stamp(when or datetime.now(timezone.utc)), module, kind, call, provider, model or "",
             input_tokens, cached_tokens, output_tokens, cost, int(error is not None), (error or "")[:300] or None,
             source or _purpose.get() or OTHER, searches, int(local)),
        )
    except Exception:  # noqa: BLE001 - the answer matters more than its receipt
        log.exception("couldn't record an AI call's usage")

def count(value) -> int | None:
    """A token count from a reply, or None when it isn't one."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


@dataclass
class _Request:
    model: str
    input: int | None
    output: int | None
    cached: int


class Meter:
    """One provider's attempt at a call. The adapter sets .model to the model it asks for and calls add() after
    every request the provider answered: a repair retry is a second request, and Claude reports one entry per
    model that ran when a refusal fell back. free: it ran on your own machine."""

    def __init__(self, provider: str, model: str = "", free: bool = False, asker: tuple[str, str] | None = None):
        self.provider, self.model, self.free = provider, model, free
        self.asker = asker
        self.searches = 0            # web searches the call paid for (Gemini research), counted apart from tokens
        self.requests: list[_Request] = []

    def add(self, input_tokens: int | None, output_tokens: int | None, cached: int = 0, model: str | None = None) -> None:
        """Tokens one request used, as the provider reported them (None when it didn't say). model: the model
        the reply says answered, when it says."""
        self.requests.append(_Request(model or self.model, input_tokens, output_tokens, cached or 0))

    def tokens(self) -> tuple[int | None, int | None, int | None]:
        """(input, cached, output) over every request, None where no request reported it."""
        def total(field: str) -> int | None:
            known = [getattr(r, field) for r in self.requests if getattr(r, field) is not None]
            return sum(known) if known else None
        return total("input"), total("cached") if self.requests else None, total("output")

    def cost(self, at: datetime) -> float | None:
        if self.free:
            return 0.0
        if not self.requests:
            return None
        total = 0.0
        for r in self.requests:
            # The model the reply names when it's in the table (a snapshot, or Claude's fallback model); otherwise
            # the one asked for (an alias the provider resolved to a name the page doesn't list).
            model = r.model if lookup(self.provider, r.model) else self.model
            part = cost(self.provider, model, r.input, r.output, r.cached, at)
            if part is None:
                return None
            total += part
        return total

    def record(self, call: str, error: str | None = None, stopped: bool = False) -> None:
        """Writes the attempt to the usage log. Never raises: a call doesn't fail over its own bookkeeping.
        stopped: Lockdown stopped it before anything was sent (error is Lockdown's reason), so it cost nothing."""
        when = datetime.now(timezone.utc)
        inp, cached, out = self.tokens()
        spent = 0.0 if stopped else None if error and not self.requests else self.cost(when)
        model = next((r.model for r in reversed(self.requests) if r.model), self.model)
        write(provider=self.provider, model=model, call=call, input_tokens=inp, cached_tokens=cached, output_tokens=out,
              cost=spent, error=error, local=self.free, searches=self.searches, asker=self.asker, when=when)


# ── Totals for Settings ────────────────────────────────────────────────

# Spent, but at a price this table doesn't know. (A failure that got no answer spent nothing.)
UNKNOWN = "cost IS NULL AND (failed = 0 OR input_tokens IS NOT NULL OR output_tokens IS NOT NULL)"
# Stopped by Lockdown before it was sent: a failure only in that it didn't happen, so counted apart.
STOPPED = f"failed = 1 AND error LIKE '{lockdown.REASON}%'"
_TOTALS = (f"COUNT(*) AS calls, COALESCE(SUM(cost), 0) AS cost, "
           f"COALESCE(SUM(CASE WHEN failed = 1 AND NOT ({STOPPED}) THEN 1 ELSE 0 END), 0) AS failed, "
           f"COALESCE(SUM(CASE WHEN {STOPPED} THEN 1 ELSE 0 END), 0) AS stopped, "
           f"COALESCE(SUM(CASE WHEN {UNKNOWN} THEN 1 ELSE 0 END), 0) AS unknown, "
           f"COALESCE(SUM(input_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens")


def _stamp(when: datetime) -> str:
    """The database's own timestamp format (db.now()), for any moment."""
    return when.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _totals(since: datetime) -> dict:
    return db.one(f"SELECT {_TOTALS} FROM core_ai_usage WHERE at >= ?", (_stamp(since),)) or {}


def _by(column: str, since: datetime) -> list[dict]:
    return db.query(f"SELECT {column} AS id, {_TOTALS} FROM core_ai_usage WHERE at >= ? GROUP BY {column} "
                    f"ORDER BY SUM(COALESCE(cost, 0)) DESC, COUNT(*) DESC", (_stamp(since),))


def summary(now: datetime | None = None, recent: int = 15) -> dict:
    """This month's total (in this machine's time zone), the last 30 days by provider and by module, and the most
    recent calls. Costs are dollars; `unknown` counts calls whose price isn't known, which aren't in `cost`;
    `stopped` counts calls Lockdown stopped, which aren't in `failed`."""
    now = (now or datetime.now()).astimezone()
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days30 = now - timedelta(days=30)
    calls = db.query(
        f"SELECT at, module, job, call, provider, model, input_tokens, cached_tokens, output_tokens, cost, failed, "
        f"error, ({UNKNOWN}) AS unknown, ({STOPPED}) AS stopped FROM core_ai_usage ORDER BY at DESC LIMIT ?", (recent,))
    for c in calls:
        c["stopped"] = bool(c["stopped"])
        c["failed"], c["unknown"] = bool(c["failed"]) and not c["stopped"], bool(c["unknown"])
    return {
        "month": {"start": _stamp(month), **_totals(month)},
        "last_30_days": {**_totals(days30), "by_provider": _by("provider", days30), "by_module": _by("module", days30)},
        "recent": calls,
        "prices_checked": CHECKED,
    }
