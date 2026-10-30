"""Readings: how one person seems to feel about you, your company, someone else or a product, judged by AI from
what's on file about them.

What's on file comes from the People module's "people.dossier" offer (family.call, answered in this app's own
process): their records, recent key points, and passages that mention the subject. A reading keeps a fingerprint of
what it was read from, so asking again with nothing new on file says so instead of spending.

After the AI answers, the evidence is checked against the records: a "quote" that isn't in them becomes a
paraphrase, a date that isn't in them is dropped, and confidence stays low when there's little on file.
"""
import hashlib
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from core.server import ai, events, family, jobs, settings, usage

from . import store

PROMPT_VERSION = "1"
DOSSIER = "people.dossier"
STANCES = ("very_warm", "warm", "mixed", "cool", "very_cool", "unknown")
MAX_EVIDENCE = 6
OUTPUT_TOKENS = 1_500              # about what a reading's answer costs, for the estimate

SYSTEM = (
    "You judge how one person feels about something, for the owner of a personal CRM, using only the owner's own "
    "records below. Address the owner as \"you\". Separate what the person said or did from what others said about "
    "them, and weigh direct, recent evidence most. When the records don't show how they feel, say the stance is "
    "unknown rather than guess. Never invent facts, quotes or dates, and add nothing from general knowledge, even "
    "about well-known people or companies."
)


class Evidence(BaseModel):
    date: str = Field(description="The date of the record it comes from, as YYYY-MM-DD exactly as in the records, or '' if it has none")
    source: str = Field(description="Where it comes from, named as in the records, e.g. 'Your notes on them' or a meeting's title")
    text: str = Field(description="Their exact words when quoting (copied word for word), otherwise a one-sentence paraphrase")
    quoted: bool = Field(description="True only when text is copied word for word from the records")
    leans: Literal["warm", "cool", "neutral"] = Field(description="Which way this piece points")


class Reading(BaseModel):
    stance: Literal["very_warm", "warm", "mixed", "cool", "very_cool", "unknown"] = Field(
        description="How they seem to feel about the subject overall; unknown when the records don't show it")
    confidence: Literal["low", "medium", "high"] = Field(
        description="How sure the records let you be: high only with several recent, direct pieces of evidence")
    summary: str = Field(description="Two or three plain sentences: how they seem to feel and why, addressed to the owner as 'you'")
    evidence: list[Evidence] = Field(description=f"At most {MAX_EVIDENCE} pieces, the most telling first")
    drivers: list[str] = Field(description="Up to 3 short phrases on what seems to shape how they feel")
    change: str = Field(description="One sentence on how it has changed over time, or '' when the dates can't tell")
    helps: list[str] = Field(description="Up to 3 short, concrete things the owner might do or ask next")
    unknowns: list[str] = Field(description="Up to 3 short phrases on what isn't on file and would change the reading")


class SedimentError(ValueError):
    pass


def _changed(person_ref: str) -> None:
    events.publish("sediment.reading.changed", {"person": person_ref})


# ── Which AI ──────────────────────────────────────────────────────────

def choice() -> str:
    return ai.resolve(settings.section("sediment")["reading_provider"], "heavy")


def provider() -> dict:
    return ai.describe(choice())


def written_by(pid: str) -> str:
    cfg = settings.section("ai")
    try:
        return f"{ai.label(pid, cfg)} ({ai.model_for(pid, cfg)})"
    except (KeyError, TypeError):
        return pid


# ── What's on file ────────────────────────────────────────────────────

def dossier(person_ref: str, about: dict | None, local: bool, voice: bool = False) -> dict:
    """The People module's answer (with `voice`, their own lines from transcripts too). Raises LookupError when
    they're not in the book, SedimentError for you."""
    try:
        return family.call(DOSSIER, id=person_ref, about=about or {}, scale="local" if local else "cloud",
                           transcripts=bool(settings.section("sediment")["transcripts"]), voice=voice)
    except family.Unavailable as e:
        raise SedimentError(str(e)) from e
    except ValueError as e:
        raise SedimentError(str(e)) from e


def subject_for(key: str) -> tuple[dict, str]:
    """The `about` the dossier takes for a subject key, and the subject's name as you'd see it."""
    if key == "me":
        return {"kind": "me"}, "You"
    if key.startswith("product:"):
        s = store.subject(key.removeprefix("product:"))
        if not s:
            raise SedimentError("That product is gone")
        return {"kind": "product", "name": s["name"], "terms": s["terms"], "summary": s["description"]}, s["name"]
    if key == "company" or key.startswith("crm:"):
        return {"ref": key}, ""     # the name comes back with the dossier
    raise SedimentError("Choose what the reading is about")


def _resolve(person_ref: str, key: str, local: bool) -> tuple[dict, str]:
    """(dossier, subject name). "company" is your employer in the book."""
    about, name = subject_for(key)
    if key == "company":
        base = dossier(person_ref, None, local)
        if not base.get("company"):
            raise SedimentError("Your company isn't in your book yet: add where you work to your own profile in People")
        about = {"ref": base["company"]["ref"]}
    d = dossier(person_ref, about, local)
    return d, name or (d.get("subject") or {}).get("name") or "Them"


def fingerprint(d: dict, key: str) -> str:
    """Changes when the records, the passages, the subject's description, the prompt or the AI change."""
    seed = "\n".join((PROMPT_VERSION, choice(), d["fingerprint"], key))
    return hashlib.sha256(seed.encode()).hexdigest()[:24]


def _subject_line(d: dict, key: str, name: str) -> str:
    s = d.get("subject") or {}
    if key == "me":
        return "you, the owner of these records"
    if key == "company":
        line = f"your company, {name}"
    elif s.get("kind") == "person":
        line = f"{name}, another person in your book"
    elif s.get("kind") == "organization":
        line = f"{name}, an organization"
    else:
        line = f"{name}, a product"
    if s.get("aliases"):
        line += f" (also called {', '.join(s['aliases'])})"
    if (s.get("summary") or "").strip():
        line += f". What you have on file about it: {s['summary'].strip()}"
    return line


def prompt(d: dict, key: str, name: str) -> str:
    first = d["first"]
    parts = [f"{d['owner']} Today is {datetime.now(UTC).strftime('%A %d %B %Y')}.",
             f"The subject: {_subject_line(d, key, name)}.",
             f"Records about {d['name']}:\n\n{d['records']}"]
    if d.get("key_points"):
        parts.append(f"Key points of recent meetings {first} was in:\n{d['key_points']}")
    if d.get("passages"):
        heading = (f"What {first} said in meetings with you, newest first:" if key == "me"
                   else f"Passages from your records that mention {name}, newest first:")
        parts.append(heading + "\n" + "\n".join(f"[{p['date']} · {p['source']}] {p['text']}" for p in d["passages"]))
    elif key != "me":
        parts.append(f"Nothing in your records about {first} mentions {name} by name.")
    parts.append(
        f"How does {first} seem to feel about {'you' if key == 'me' else name}? Judge it from these records only. "
        "Give the stance, your confidence, a short summary, the evidence (dated and sourced as in the records), what "
        "seems to drive it, how it has changed, what might help, and what isn't on file.")
    return "\n\n".join(parts)


def _fold(text: str) -> str:
    return " ".join(re.sub(r"[“”\"‘’']", "", text).lower().split())


def check(answer: Reading, d: dict) -> dict:
    """The answer as kept: quotes and dates checked against the records, confidence held down on thin records."""
    corpus = "\n".join([d["records"], d.get("key_points") or "",
                        *(f"{p['date']} {p['source']} {p['text']}" for p in d.get("passages") or [])])
    folded = _fold(corpus)
    evidence = []
    for e in answer.evidence[:MAX_EVIDENCE]:
        text = e.text.strip()
        if not text:
            continue
        quoted = bool(e.quoted) and len(_fold(text)) >= 8 and _fold(text) in folded
        evidence.append({"date": e.date if e.date and e.date in corpus else "", "source": e.source.strip(),
                         "text": text, "quoted": quoted, "leans": e.leans})
    confidence = answer.confidence
    if answer.stance == "unknown" or not d["material"] or not evidence:
        confidence = "low"
    elif confidence == "high" and len(evidence) < 3:
        confidence = "medium"
    return {"stance": answer.stance, "confidence": confidence, "summary": answer.summary.strip(), "evidence": evidence,
            "drivers": [x.strip() for x in answer.drivers if x.strip()][:3], "change": (answer.change or "").strip(),
            "helps": [x.strip() for x in answer.helps if x.strip()][:3],
            "unknowns": [x.strip() for x in answer.unknowns if x.strip()][:3]}


def estimate(text: str, prov: dict) -> float | None:
    """Dollars a cloud reading of this much text costs, roughly (four characters to a token), or None on this Mac."""
    if prov["local"] or not prov["model"]:
        return None
    p = usage.price(prov["provider"], prov["model"])
    if p is None:
        return None
    return round((len(text) / 4 * p[0] + OUTPUT_TOKENS * p[1]) / 1e6, 4)


# ── Asking and reading ────────────────────────────────────────────────

def request(person_ref: str, key: str, again: bool = False) -> dict:
    """Queues a reading, unless nothing is new on file since the last one of the same subject (then says when that was)."""
    prov = provider()
    d, name = _resolve(person_ref, key, prov["local"])
    ref = d["ref"]
    last = store.latest_done(ref, key)
    if not again and last and last["fingerprint"] == fingerprint(d, key):
        return {"unchanged": True, "since": last["read_at"], "reading": store.reading_out(last)}
    rid = store.add_reading(ref, d["name"], key, name)
    jobs.enqueue("sediment", "read", rid)
    _changed(ref)
    return {"unchanged": False, "reading": store.reading_out(store.reading(rid))}  # type: ignore[arg-type]


def retry(reading_id: str) -> dict:
    row = store.reading(reading_id)
    if not row:
        raise SedimentError("That reading is gone")
    store.requeue_reading(reading_id)
    jobs.enqueue("sediment", "read", reading_id)
    _changed(row["person_ref"])
    return store.reading_out(store.reading(reading_id))  # type: ignore[arg-type]


def read(job: jobs.Job) -> None:
    """Takes one reading. A failure stays on the reading with its reason, for Try again; when the AI can't answer for
    now (memory, a rate limit), the job waits instead, picks up by itself, and can be told to go ahead anyway."""
    row = store.reading(job.target)
    if not row or row["status"] == "done":
        return

    def fail(text: str) -> None:
        store.fail_reading(row["id"], text)
        _changed(row["person_ref"])

    prov = provider()
    if not prov["ready"]:
        return fail(prov["reason"] or "No AI is set up for this yet (Settings → AI)")
    job.stage("Gathering what's on file")
    try:
        d, name = _resolve(row["person_ref"], row["subject_key"], prov["local"])
    except LookupError:
        return fail("They're no longer in your book")
    except SedimentError as e:
        return fail(str(e))
    text = prompt(d, row["subject_key"], name)
    job.stage("Reading")
    try:
        answer, pid = ai.structured(text, SYSTEM, Reading, choice(), purpose="Sediment readings")
    except ai.AIError as e:
        if e.provider_down:   # not enough memory, a rate limit, an outage: wait (and resume) rather than fail
            raise jobs.Wait(str(e)) from e
        return fail(str(e))
    body = check(answer, d)  # type: ignore[arg-type]
    body["estimate"] = estimate(text + SYSTEM, prov)
    body["characters"] = len(text)
    store.finish_reading(row["id"], stance=body.pop("stance"), confidence=body.pop("confidence"), body=body,
                         fingerprint=fingerprint(d, row["subject_key"]), written_by=written_by(pid),
                         person_name=d["name"], subject_name=name)
    _changed(row["person_ref"])
