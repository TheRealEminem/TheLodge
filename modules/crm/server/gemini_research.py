"""The Lodge researching a person itself, with Gemini and Google Search (Chunk 19).

A run follows the research brief: six focused questions, each answered by Gemini with Google Search, then one report
written from the answers in the brief's shape, carrying its ref. The report goes to the Inbox like one you pasted
and waits for your OK. Nothing runs unless you start it, and a run stops before it would pass the month's budget.

Levels, which models do the work:
    quick    Flash-Lite asks and writes. Cheap, but it often answers without searching
    better   Flash asks and writes                                       the default, through Batch
    best     Flash asks; the Pro model checks what's missing, has it asked, and writes
Each can go through Google's Batch API: half the token price, answers within a day (usually minutes). Google bills
each search the model runs the same either way.

Costs are counted from what Google reports for each answer: tokens at the list prices in PRICES (as of PRICES_AS_OF),
halved for Batch, plus every search at $14 per 1,000. Google gives the first 5,000 searches a month free on
Gemini 3 and newer; that isn't subtracted here, so the figures are what it would cost past the free searches.

    crm_research_runs   one per person per run (the table is in store.py)
"""
import json
import logging
import re
from datetime import UTC, datetime

import httpx

from core.server import db, events, jobs, lockdown, settings
from core.server import usage as tally   # absorb() has a local named usage

from . import ingest, research

log = logging.getLogger("crm.gemini_research")

API = "https://generativelanguage.googleapis.com/v1beta"
PRICES_AS_OF = "2026-10-19"
# Dollars per 1M tokens: input, output (thinking included), cached input. Standard tier; Batch is half.
PRICES = {
    "gemini-3.5-flash-lite": (0.30, 2.50, 0.03),
    "gemini-3.1-flash-lite": (0.25, 1.50, 0.025),
    "gemini-3.8-flash": (0.75, 3.75, 0.075),
    "gemini-3.6-flash": (0.75, 3.75, 0.075),
    "gemini-4-argon": (2.00, 10.00, 0.10),
    "gemini-3.1-pro-preview": (2.00, 12.00, 0.20),
}
SEARCH_PRICE = 14 / 1000
BATCH_DISCOUNT = 0.5

LEVELS = {
    "quick": {"label": "Quick", "ask": "gemini-3.5-flash-lite", "check": None, "write": "gemini-3.5-flash-lite",
              "hint": "Gemini Flash-Lite searches and writes. The cheapest, but it often skips searching, so reports are thin."},
    "better": {"label": "Better", "ask": "gemini-3.8-flash", "check": None, "write": "gemini-3.8-flash",
               "hint": "Gemini Flash searches and writes. Searches thoroughly and writes a full, sourced report. Recommended."},
    "best": {"label": "Best", "ask": "gemini-3.8-flash", "check": "gemini-4-argon", "write": "gemini-4-argon",
             "hint": "Flash searches, then Gemini's Pro model checks what's missing, has it looked up, and writes."},
}
MODEL_NAMES = {"gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite", "gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite",
               "gemini-3.8-flash": "Gemini 3.8 Flash", "gemini-3.6-flash": "Gemini 3.6 Flash",
               "gemini-4-argon": "Gemini 4 Argon", "gemini-3.1-pro-preview": "Gemini 3.1 Pro"}

ANGLES = [
    ("Who they are now", "What is their current role and organization, and where are they based? What confirms this "
                         "is the right person, and is there anyone else with the same name who could be confused with them?"),
    ("Career", "What were their earlier roles and employers, with dates, and where did they study?"),
    ("Affiliations", "Which boards, advisory roles, investments, nonprofits or associations are they part of, with dates?"),
    ("Public work", "What have they published, said or built in public in the last five years: articles, talks, "
                    "interviews, podcasts, projects, patents, awards?"),
    ("People around them", "Who do they work most closely with: co-founders, partners, colleagues, collaborators?"),
    ("Recent news", "What news is there about them, or about their organization involving them, in the last 12 months?"),
]
MAX_FOLLOW_UPS = 3
SOURCES_PER_ANSWER = 10
UNFINISHED = ("queued", "running", "waiting")

# What a typical run uses, for estimates before it starts (tokens in, tokens out, searches per answer).
TYPICAL = {"ask": (1_500, 1_500, 2), "ask_thinking": (1_500, 3_500, 2), "check": (12_000, 3_500, 0),
           "write": (12_000, 4_000, 0), "write_thinking": (12_000, 7_000, 0)}

ASK_SYSTEM = (
    "You look up one specific person for the owner of a personal CRM, using Google Search. Answer only the question "
    "asked, about this person and no one else with the same name. Give concrete facts, with the month and year where "
    "you can, and name the source of each. If a result could be about someone else with the same name, say so and why. "
    "Always search Google before you answer, even if you think you know: at least one search, and up to three, "
    "trying the name with their organization, their city or their field. Only after that, if nothing is about this "
    "person, say \"Nothing found.\" Never guess or fill in from general knowledge. Keep it under 300 words."
)
CHECK_SYSTEM = (
    "You review research notes about one person before a profile is written from them. Reply with JSON only: "
    "{\"same_person\": true or false, \"gaps\": \"one sentence\", \"follow_ups\": [up to 3 questions]}. same_person is "
    "false if the notes may mix up two people. follow_ups are specific questions worth one more web search each, about "
    "facts that matter for the profile and are missing or contradictory; an empty list if nothing important is missing."
)
WRITE_SYSTEM = (
    "You write research profiles of people for the owner of a personal CRM, from research notes you're given. Use only "
    "facts in the notes, never your own knowledge. After each claim that matters, cite its source by link. If notes "
    "disagree, say so. If they may describe more than one person, say so in the identity line and lower the confidence."
)


class ResearchRunError(ValueError):
    pass


class GoogleError(RuntimeError):
    def __init__(self, status: int, text: str):
        super().__init__(text)
        self.status = status

    @property
    def retry(self) -> bool:
        return self.status in (0, 408, 429) or self.status >= 500


def _now() -> str:
    return db.now()


def _changed(person_id: str | None = None) -> None:
    events.publish("crm.research.changed", {"id": person_id})


# ── Google ────────────────────────────────────────────────────────────

def api_key() -> str:
    return (settings.section("ai").get("gemini_api_key") or "").strip()


def _call(method: str, path: str, **kw) -> dict:
    """One request to the Gemini API. Raises GoogleError (status 0 when Google couldn't be reached)."""
    try:
        r = httpx.request(method, f"{API}/{path}", headers={"x-goog-api-key": api_key()}, timeout=kw.pop("timeout", 300), **kw)
    except httpx.HTTPError as e:
        raise GoogleError(0, f"Couldn't reach Google: {e or type(e).__name__}") from e
    if r.status_code in (401, 403) or (r.status_code == 400 and "API_KEY_INVALID" in r.text):
        raise GoogleError(r.status_code, "Google didn't accept the Gemini API key (Settings → AI)")
    if r.status_code == 404:
        raise GoogleError(404, f"Google doesn't offer that model to this key: {r.text[:200]}")
    if r.status_code >= 400:
        raise GoogleError(r.status_code, f"Google returned {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


def _request(system: str, prompt: str, search: bool, json_out: bool = False) -> dict:
    body: dict = {"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if search:
        body["tools"] = [{"google_search": {}}]
    if json_out:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    return body


def parse(resp: dict) -> dict:
    """{text, error, usage {in, out, cached}, searches [queries], sources [{url, title}]} from a generateContent reply."""
    cand = (resp.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    meta = cand.get("groundingMetadata") or {}
    sources, seen = [], set()
    for chunk in meta.get("groundingChunks") or []:
        web = chunk.get("web") or {}
        if web.get("uri") and web["uri"] not in seen:
            seen.add(web["uri"])
            sources.append({"url": web["uri"], "title": web.get("title") or ""})
    um = resp.get("usageMetadata") or {}
    usage = {"in": int(um.get("promptTokenCount") or 0),
             "out": int(um.get("candidatesTokenCount") or 0) + int(um.get("thoughtsTokenCount") or 0),
             "cached": int(um.get("cachedContentTokenCount") or 0)}
    error = None if text.strip() else f"Gemini returned no text ({cand.get('finishReason') or 'it may have blocked the request'})"
    return {"text": text.strip(), "error": error, "usage": usage, "searches": list(meta.get("webSearchQueries") or []),
            "sources": sources[:SOURCES_PER_ANSWER]}


def generate(model: str, body: dict) -> dict:
    return parse(_call("POST", f"models/{model}:generateContent", json=body))


def batch_create(model: str, requests: list[tuple[str, dict]]) -> str:
    body = {"batch": {"display_name": "the-lodge-research", "input_config": {"requests": {"requests": [
        {"request": req, "metadata": {"key": key}} for key, req in requests]}}}}
    out = _call("POST", f"models/{model}:batchGenerateContent", json=body, timeout=120)
    if not out.get("name"):
        raise GoogleError(500, "Google didn't give the batch a name")
    return out["name"]


def batch_status(name: str) -> tuple[str, dict[str, dict] | None, str | None]:
    """(pending | running | succeeded | failed | cancelled | expired, {key: parsed answer} once succeeded, error)."""
    j = _call("GET", name, timeout=60)
    meta = j.get("metadata") or {}
    state = (meta.get("state") or j.get("state") or "").rsplit("_", 1)[-1].lower() or "pending"
    if state not in ("pending", "running", "succeeded", "failed", "cancelled", "expired"):
        state = "pending"
    if state == "failed":
        return state, None, str((j.get("error") or {}).get("message") or "Google says the batch failed")
    if state != "succeeded":
        return state, None, None
    holders = [j.get("response") or {}, meta.get("output") or {}, j.get("dest") or {}]
    items = next((h["inlinedResponses"]["inlinedResponses"] if isinstance(h.get("inlinedResponses"), dict)
                  else h["inlinedResponses"] for h in holders if h.get("inlinedResponses")), [])
    out = {}
    for item in items:
        key = (item.get("metadata") or {}).get("key", "")
        if item.get("error"):
            out[key] = {"text": "", "error": str(item["error"].get("message") or item["error"]), "usage": {}, "searches": [], "sources": []}
        else:
            out[key] = parse(item.get("response") or {})
    return state, out, None


def resolve_link(url: str) -> str:
    """Search sources come as Google redirect links that stop working after a while: follow one to where it goes."""
    if "grounding-api-redirect" not in url:
        return url
    try:
        r = httpx.head(url, follow_redirects=False, timeout=8)
        return r.headers.get("location") or url
    except httpx.HTTPError:
        return url


# ── Money ─────────────────────────────────────────────────────────────

def cost(model: str, usage: dict, searches: int, batch: bool) -> float:
    pin, pout, pcached = PRICES.get(model, PRICES["gemini-4-argon"])   # an unknown model is priced high, not free
    cached = min(usage.get("cached", 0), usage.get("in", 0))
    tokens = ((usage.get("in", 0) - cached) * pin + cached * pcached + usage.get("out", 0) * pout) / 1e6
    return round(tokens * (BATCH_DISCOUNT if batch else 1) + searches * SEARCH_PRICE, 5)


def _thinks(model: str) -> bool:
    return "lite" not in model


def estimate(level: str, batch: bool) -> float:
    """What one person costs at this level, typically (searches past the free 5,000 a month counted)."""
    lv = LEVELS[level]
    ask_in, ask_out, per = TYPICAL["ask_thinking" if _thinks(lv["ask"]) else "ask"]
    total = cost(lv["ask"], {"in": ask_in * len(ANGLES), "out": ask_out * len(ANGLES)}, per * len(ANGLES), batch)
    if lv["check"]:
        c_in, c_out, _ = TYPICAL["check"]
        total += cost(lv["check"], {"in": c_in, "out": c_out}, 0, batch)
        total += cost(lv["ask"], {"in": ask_in * 2, "out": ask_out * 2}, per * 2, batch)   # about two follow-ups
    w_in, w_out, _ = TYPICAL["write_thinking" if _thinks(lv["write"]) else "write"]
    total += cost(lv["write"], {"in": w_in, "out": w_out}, 0, batch)
    return round(total, 3)


def month_start() -> str:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def spent_this_month() -> float:
    row = db.one("SELECT COALESCE(SUM(cost), 0) AS n FROM crm_research_runs WHERE created_at >= ?", (month_start(),))
    return round(float(row["n"]), 4)


def budget() -> int:
    return int(settings.section("crm")["research_budget"])


def overview() -> dict:
    """For Settings and the start dialog: the levels with typical costs, the budget and what's been spent."""
    ready = bool(api_key()) and not locked()
    return {
        "ready": ready, "reason": locked() or (None if ready else "Add a Gemini API key in Settings → AI first"),
        "level": settings.section("crm")["research_level"], "batch": settings.section("crm")["research_batch"],
        "budget": budget(), "spent": spent_this_month(), "prices_as_of": PRICES_AS_OF, "warn_over": tally.warn_over(),
        "levels": [{"id": k, "label": v["label"], "hint": v["hint"],
                    "models": sorted({MODEL_NAMES.get(m, m) for m in (v["ask"], v["check"], v["write"]) if m}),
                    "estimate": estimate(k, False), "estimate_batch": estimate(k, True)} for k, v in LEVELS.items()],
        "runs": [_out(r) for r in db.query("SELECT * FROM crm_research_runs ORDER BY created_at DESC LIMIT 20")],
    }


# ── Runs ──────────────────────────────────────────────────────────────

def _out(r: dict) -> dict:
    name = db.one("SELECT name FROM crm_entities WHERE id = ?", (r["entity_id"],))
    return {"id": r["id"], "person_id": r["entity_id"], "person": name["name"] if name else None, "level": r["level"],
            "batch": bool(r["batch"]), "status": r["status"], "stage": r["stage"], "error": r["error"],
            "searches": r["searches"], "cost": round(r["cost"], 4), "inbox_id": r["inbox_id"],
            "created_at": r["created_at"], "finished_at": r["finished_at"]}


def locked() -> str | None:
    """Why research by Gemini is off right now (Lockdown), or None. "Copy research brief" stays: you take it elsewhere."""
    return lockdown.blocked("Research by Gemini")


def run_of(person_id: str) -> dict | None:
    """The latest run on someone, finished or not."""
    r = db.one("SELECT * FROM crm_research_runs WHERE entity_id = ? ORDER BY created_at DESC LIMIT 1", (person_id,))
    return _out(r) if r else None


def start(person_ids: list[str], level: str, batch: bool) -> dict:
    """Start research on these people, as many as fit in what's left of the month's budget. Someone already being
    researched, or who can't be (no surname), is skipped and said why."""
    if level not in LEVELS:
        raise ResearchRunError("Unknown level")
    if (why := locked()):
        raise ResearchRunError(why)
    if not api_key():
        raise ResearchRunError("Add a Gemini API key in Settings → AI first")
    each = estimate(level, batch)
    room = budget() - spent_this_month() - _committed()
    started, skipped = [], []
    for pid in dict.fromkeys(person_ids):
        try:
            sub = research.subject(pid)
        except research.ResearchError as e:
            skipped.append({"id": pid, "reason": str(e)})
            continue
        if db.one(f"SELECT 1 AS x FROM crm_research_runs WHERE entity_id = ? AND status IN {UNFINISHED}", (pid,)):
            skipped.append({"id": pid, "reason": f"{sub.person.name} is already being researched"})
            continue
        if each > room:
            skipped.append({"id": pid, "reason": "This month's research budget is used up"})
            continue
        room -= each
        now = _now()
        db.execute("INSERT INTO crm_research_runs (id, entity_id, level, batch, status, stage, findings, usage, created_at, updated_at) "
                   "VALUES (?, ?, ?, ?, 'queued', 'ask', '[]', '{}', ?, ?)", (db.new_id(), pid, level, int(batch), now, now))
        started.append(pid)
    if started:
        jobs.enqueue("crm", "research_advance", "scheduled")
        _changed()
    return {"started": len(started), "skipped": skipped, "estimate_each": each}


def _committed() -> float:
    """What runs still under way are likely to cost on top of what they've spent."""
    rows = db.query(f"SELECT level, batch, cost FROM crm_research_runs WHERE status IN {UNFINISHED}")
    return sum(max(0.0, estimate(r["level"], bool(r["batch"])) - r["cost"]) for r in rows)


def cancel(run_id: str) -> dict:
    r = db.one("SELECT * FROM crm_research_runs WHERE id = ?", (run_id,))
    if r is None:
        raise ResearchRunError("That research run isn't on record")
    if r["status"] in UNFINISHED:
        if r["batch_name"] and not db.one("SELECT 1 AS x FROM crm_research_runs WHERE batch_name = ? AND id != ? AND status IN "
                                          f"{UNFINISHED}", (r["batch_name"], run_id)):
            try:
                _call("POST", f"{r['batch_name']}:cancel", json={})
            except GoogleError as e:
                log.warning("couldn't cancel %s: %s", r["batch_name"], e)
        _update(run_id, status="cancelled", batch_name=None, finished_at=_now())
    _changed(r["entity_id"])
    return _out(db.one("SELECT * FROM crm_research_runs WHERE id = ?", (run_id,)))


def retry(run_id: str) -> dict:
    r = db.one("SELECT * FROM crm_research_runs WHERE id = ?", (run_id,))
    if r is None or r["status"] not in ("failed", "cancelled"):
        raise ResearchRunError("Only a run that failed or was cancelled can be tried again")
    _update(run_id, status="queued", error=None, batch_name=None, finished_at=None)
    jobs.enqueue("crm", "research_advance", "scheduled")
    _changed(r["entity_id"])
    return _out(db.one("SELECT * FROM crm_research_runs WHERE id = ?", (run_id,)))


def _update(run_id: str, **fields) -> None:
    for k in ("findings", "usage"):
        if k in fields:
            fields[k] = json.dumps(fields[k])
    fields["updated_at"] = _now()
    db.execute(f"UPDATE crm_research_runs SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), run_id))


# ── The stages ────────────────────────────────────────────────────────

def _who(sub: research.Subject) -> str:
    """Who to look for, for a web search: what's known about them, but not your own tags for them."""
    known = [k for k in sub.known if not k.startswith("- My tags")]
    return f"The person: {sub.person.name}\nWhat the owner knows about them:\n" + "\n".join(known)


def _model(r: dict, stage: str) -> str:
    lv = LEVELS[r["level"]]
    return lv["write"] if stage == "write" else lv["check"] if stage == "check" else lv["ask"]


def requests_for(r: dict) -> list[tuple[str, dict]]:
    """The requests a run's current stage sends: (key, generateContent body)."""
    sub = research.subject(r["entity_id"])
    findings = json.loads(r["findings"] or "[]")
    stage = r["stage"]
    if stage == "ask":
        return [(f"{r['id']}:ask:{i}", _request(ASK_SYSTEM, f"{_who(sub)}\n\nToday is {sub.today}.\n\nQuestion: {q}", True))
                for i, (_, q) in enumerate(ANGLES)]
    if stage == "more":
        asked = [f for f in findings if f.get("follow_up") and not f.get("text")]
        return [(f"{r['id']}:more:{i}", _request(ASK_SYSTEM, f"{_who(sub)}\n\nToday is {sub.today}.\n\nQuestion: {f['question']}", True))
                for i, f in enumerate(asked)]
    if stage == "check":
        return [(f"{r['id']}:check", _request(CHECK_SYSTEM, f"{_who(sub)}\n\nResearch notes:\n\n{_notes(findings)}", False, json_out=True))]
    if stage == "write":
        prompt = (f"{research.brief(r['entity_id'])}\n\n---\n\nResearch notes, gathered with Google Search on {sub.today}:\n\n"
                  f"{_notes(findings)}\n\n---\n\nWrite the report the brief asks for, from these notes only. Follow its "
                  "format exactly, including the title, the Lodge ref line and the Identity confidence line. Cite "
                  "sources by their links. If the notes found little, keep the report short and say so plainly.")
        return [(f"{r['id']}:write", _request(WRITE_SYSTEM, prompt, False))]
    return []


def _notes(findings: list[dict]) -> str:
    out = []
    for f in findings:
        if not f.get("text"):
            continue
        block = f"## {f['angle']}\n{f['text']}"
        if f.get("sources"):
            block += "\nSources:\n" + "\n".join(f"- {s['title'] or s['url']}: {s['url']}" for s in f["sources"])
        out.append(block)
    return "\n\n".join(out) or "(Nothing was found.)"


def absorb(r: dict, answers: dict[str, dict]) -> None:
    """Takes a stage's answers into the run, counts what they cost, and moves it to its next stage."""
    stage, model, batch = r["stage"], _model(r, r["stage"]), bool(r["batch"])
    findings = json.loads(r["findings"] or "[]")
    usage = json.loads(r["usage"] or "{}")
    spent, searches, errors = 0.0, 0, []
    open_ = [f for f in findings if f.get("follow_up") and not f.get("text")]   # in the order they were asked
    for key, a in sorted(answers.items(), key=lambda kv: int(kv[0].rsplit(":", 1)[1]) if kv[0].rsplit(":", 1)[1].isdigit() else 0):
        n = len(a.get("searches") or [])
        searches += n
        answer_cost = cost(model, a.get("usage") or {}, n, batch)
        spent += answer_cost
        tally.record("gemini", model, (a.get("usage") or {}).get("in", 0), (a.get("usage") or {}).get("out", 0), searches=n,
                     cost=answer_cost, source="Researching people")
        u = usage.setdefault(model, {"in": 0, "out": 0, "cached": 0, "calls": 0})
        for k in ("in", "out", "cached"):
            u[k] += (a.get("usage") or {}).get(k, 0)
        u["calls"] += 1
        if a.get("error"):
            errors.append(a["error"])
        a["sources"] = [{**s, "url": resolve_link(s["url"])} for s in a.get("sources") or []]
        if stage == "ask":
            i = int(key.rsplit(":", 1)[1])
            findings.append({"angle": ANGLES[i][0], "question": ANGLES[i][1], "text": a.get("text") or "",
                             "sources": a["sources"], "searches": a.get("searches") or []})
        elif stage == "more":
            i = int(key.rsplit(":", 1)[1])
            if i < len(open_):
                open_[i].update(text=a.get("text") or "Nothing found.", sources=a["sources"], searches=a.get("searches") or [])
    fields: dict = {"findings": findings, "usage": usage, "searches": r["searches"] + searches,
                    "cost": round(r["cost"] + spent, 5), "batch_name": None, "status": "running", "error": None}
    level = LEVELS[r["level"]]
    if stage == "ask":
        if not any(f["text"] for f in findings):
            fields.update(status="failed", error=errors[0] if errors else "Gemini found nothing", finished_at=_now())
        else:
            fields["stage"] = "check" if level["check"] else "write"
    elif stage == "check":
        follow = _follow_ups(answers)
        for q in follow:
            findings.append({"angle": f"Follow-up: {q}", "question": q, "text": "", "sources": [], "searches": [], "follow_up": True})
        fields["stage"] = "more" if follow else "write"
    elif stage == "more":
        fields["stage"] = "write"
    elif stage == "write":
        a = next(iter(answers.values()), {})
        if not a.get("text"):
            fields.update(status="failed", error=a.get("error") or "Gemini wrote nothing", finished_at=_now())
        else:
            fields.update(_file(r, a["text"], fields["searches"], fields["cost"]))
    _update(r["id"], **fields)
    _changed(r["entity_id"])


def _follow_ups(answers: dict[str, dict]) -> list[str]:
    text = next(iter(answers.values()), {}).get("text") or ""
    try:
        data = json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip()).strip())
    except ValueError:
        return []
    qs = data.get("follow_ups") if isinstance(data, dict) else None
    return [str(q).strip() for q in (qs or []) if str(q).strip()][:MAX_FOLLOW_UPS]


def _file(r: dict, report: str, searches: int, spent: float) -> dict:
    """The report into the Inbox, as research on this person, with how it was made at the end."""
    sub = research.subject(r["entity_id"])
    lv = LEVELS[r["level"]]
    models = " and ".join(dict.fromkeys(MODEL_NAMES.get(m, m) for m in (lv["ask"], lv["check"], lv["write"]) if m))
    footer = (f"\n\n---\nResearched by The Lodge with {models}{' through Google Batch' if r['batch'] else ''} on {sub.today}: "
              f"{searches} Google search{'' if searches == 1 else 'es'}, about ${spent:.2f}.")
    row = ingest.create_note_job(report.strip() + footer, sub.title, None, r["entity_id"])
    return {"stage": "done", "status": "done", "inbox_id": row["id"], "finished_at": _now()}


# ── The job ───────────────────────────────────────────────────────────

def handle_advance(job: jobs.Job) -> None:
    """Moves every run along: collects finished batches, then sends each waiting stage, batched together per model
    where that was asked for. Safe to run twice: a stage's answers are only taken in once."""
    if locked() or not api_key():
        return
    for name in [x["batch_name"] for x in db.query(
            f"SELECT DISTINCT batch_name FROM crm_research_runs WHERE batch_name IS NOT NULL AND status IN {UNFINISHED}")]:
        try:
            state, answers, error = batch_status(name)
        except GoogleError as e:
            log.warning("checking %s: %s", name, e)
            continue
        runs = db.query("SELECT * FROM crm_research_runs WHERE batch_name = ?", (name,))
        if state == "succeeded" and answers is not None:
            for r in runs:
                mine = {k: v for k, v in answers.items() if k.startswith(r["id"] + ":")}
                if mine:
                    absorb(r, mine)
                else:
                    _update(r["id"], status="failed", error="Google's batch came back without this person's answers",
                            batch_name=None, finished_at=_now())
        elif state in ("failed", "cancelled", "expired"):
            for r in runs:
                _update(r["id"], status="failed", error=error or f"Google's batch {state}", batch_name=None, finished_at=_now())
                _changed(r["entity_id"])

    ready = db.query(f"SELECT * FROM crm_research_runs WHERE status IN {UNFINISHED} AND batch_name IS NULL ORDER BY created_at")
    batches: dict[str, list[tuple[dict, list[tuple[str, dict]]]]] = {}
    for r in ready:
        if spent_this_month() >= budget():
            _update(r["id"], status="waiting", error="Waiting: this month's research budget is used up")
            _changed(r["entity_id"])
            continue
        try:
            reqs = requests_for(r)
        except research.ResearchError as e:
            _update(r["id"], status="failed", error=str(e), finished_at=_now())
            continue
        if not reqs:
            continue
        if r["batch"]:
            batches.setdefault(_model(r, r["stage"]), []).append((r, reqs))
            continue
        _run_now(job, r, reqs)

    for model, group in batches.items():
        job.stage(f"Sending {len(group)} to Google Batch")
        try:
            name = batch_create(model, [req for _, reqs in group for req in reqs])
        except GoogleError as e:
            for r, _ in group:
                _update(r["id"], status="waiting" if e.retry else "failed", error=str(e),
                        **({} if e.retry else {"finished_at": _now()}))
                _changed(r["entity_id"])
            continue
        for r, _ in group:
            _update(r["id"], status="running", batch_name=name, error=None)
            _changed(r["entity_id"])


def _run_now(job: jobs.Job, r: dict, reqs: list[tuple[str, dict]]) -> None:
    """A run not batched goes through all its stages here, one request at a time."""
    while reqs:
        job.stage(f"Researching ({r['stage']})")
        answers, stop = {}, None
        for key, body in reqs:
            try:
                answers[key] = generate(_model(r, r["stage"]), body)
            except GoogleError as e:
                if e.retry:
                    stop = e
                    break
                answers[key] = {"text": "", "error": str(e), "usage": {}, "searches": [], "sources": []}
        if stop:
            _update(r["id"], status="waiting", error=f"Waiting for Google: {stop}")
            _changed(r["entity_id"])
            return
        absorb(r, answers)
        r = db.one("SELECT * FROM crm_research_runs WHERE id = ?", (r["id"],))
        if r["status"] not in UNFINISHED or spent_this_month() >= budget():
            return
        reqs = requests_for(r)


def seconds() -> int:
    """Every minute while a run is under way (a batch is checked on), otherwise not at all."""
    if locked():
        return 0
    return 60 if db.one(f"SELECT 1 AS x FROM crm_research_runs WHERE status IN {UNFINISHED}") else 0
