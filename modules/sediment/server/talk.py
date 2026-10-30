"""A portrait of someone, and rehearsals: a conversation with them as the AI plays them from what's on file.

The portrait is a written model of the whole person (how they talk, what they care about, how they seem to see you,
what's left open), written from their records and their own lines in transcripts, and written again when those
change, like the People module's overviews. A rehearsal reply is grounded in the portrait and the records: anything the
AI makes up is listed as a guess (copied from the reply, so the page can mark it), and what the rest rests on is listed
as grounds, for "Why?". Phrases that aren't in the reply are dropped.

It is a simulation for practice, and says so: on the page, in the prompt, and when asked. It never invents facts about
health, family, money, legal matters or private life, and nothing it says goes back into People.
"""
import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from core.server import ai, events, jobs, settings

from . import readings, store
from .readings import SedimentError

PROMPT_VERSION = "1"
HISTORY = 16                  # earlier lines sent along with each reply
MAX_LINE = 2_000
MAX_SCENARIO = 600
PORTRAIT_KINDS = ("portrait",)

PORTRAIT_SYSTEM = (
    "You write a portrait of one person for the owner of a personal CRM, from the owner's own records, so that a "
    "rehearsal can play them faithfully. Address the owner as \"you\". Use only what the records say: never invent or "
    "guess, and add nothing from general knowledge, even about well-known people. Never speculate about their health, "
    "family, money, legal matters or private life. If the records say little, say so plainly."
)


def reply_system(name: str, first: str) -> str:
    return (
        f"You are playing {name} in a rehearsal, so the owner of a personal CRM can practice a conversation with "
        f"{first}. It is a simulation built from the owner's own records, for the owner's practice only. Speak as "
        f"{first}, in the first person, to the owner, the way the portrait and records show {first} talks, and keep "
        "replies short, like a real conversation (one to four sentences unless asked for more). Base what you say on "
        "the portrait and records. Where they don't say, you may answer the way the records suggest "
        f"{first} would, but copy every such made-up phrase, word for word, into `guesses`. Put what the records do "
        "support into `grounds`, each with the record it rests on. Never invent facts about their health, family, "
        "relationships, money, legal matters, beliefs or private life: if the owner asks, deflect the way they might "
        "(\"I'd rather not get into that\"). If asked whether you are real, an AI or a simulation, say plainly that "
        "you are a simulation built from the owner's notes. Don't play a caricature, and don't agree just to please."
    )


class Ground(BaseModel):
    phrase: str = Field(description="Words copied exactly from your reply")
    source: str = Field(description="The record it rests on, named as in the records, with its date when it has one")


class Reply(BaseModel):
    reply: str = Field(description="What they say next, in the first person: usually one to four sentences")
    guesses: list[str] = Field(description="Every phrase in the reply that the records don't support, copied word for word; empty if none")
    grounds: list[Ground] = Field(description="Phrases in the reply that the records support, each with its record")


def _changed(person_ref: str) -> None:
    events.publish("sediment.talk.changed", {"person": person_ref})


def _today() -> str:
    return datetime.now(UTC).strftime("%A %d %B %Y")


# ── Which AI ──────────────────────────────────────────────────────────

def choice() -> str:
    return ai.resolve(settings.section("sediment")["talk_provider"], "light")


def provider() -> dict:
    return ai.describe(choice())


def _dossier(person_ref: str) -> dict:
    # Each turn sends the records again, so they go at the local size even to a cloud AI: cheaper, and enough.
    return readings.dossier(person_ref, None, True, voice=True)


def _voice(d: dict) -> str:
    return "\n".join(f"[{v['date']} · {v['meeting']}] {v['text']}" for v in d.get("voice") or [])


# ── The portrait ──────────────────────────────────────────────────────

def fingerprint(d: dict) -> str:
    seed = "\n".join((PROMPT_VERSION, choice(), d["fingerprint"]))
    return hashlib.sha256(seed.encode()).hexdigest()[:24]


def _portrait_job(person_ref: str) -> dict | None:
    return jobs.latest("sediment", [person_ref]).get(person_ref)


def portrait_state(person_ref: str) -> dict:
    """The portrait as it stands, whether it's current, and the work on it. A missing or out-of-date one is asked for
    straight away, unless the last try failed (that shows, with Try again)."""
    prov = provider()
    d = _dossier(person_ref)
    ref = d["ref"]
    row = store.portrait(ref)
    job = _portrait_job(ref)
    current = bool(row and row["fingerprint"] == fingerprint(d))
    unfinished = job and job["status"] in jobs.UNFINISHED
    if prov["ready"] and d["material"] and not current and not unfinished and not (job and job["status"] == "error"):
        jobs.enqueue("sediment", "portrait", ref)
        job = _portrait_job(ref)
    return {"portrait": {"body": row["body"], "written_by": row["written_by"], "created_at": row["created_at"], "current": current} if row else None,
            "job": job, "material": d["material"], "voice": len(d.get("voice") or []),
            "ready": prov["ready"], "reason": prov["reason"], "provider": prov["label"], "local": prov["local"]}


def redo_portrait(person_ref: str) -> dict:
    d = _dossier(person_ref)
    store.stale_portrait(d["ref"])
    jobs.enqueue("sediment", "portrait", d["ref"])
    _changed(d["ref"])
    return portrait_state(d["ref"])


def portrait_prompt(d: dict) -> str:
    first = d["first"]
    parts = [f"{d['owner']} Today is {_today()}.", f"Records about {d['name']}:\n\n{d['records']}"]
    if d.get("key_points"):
        parts.append(f"Key points of recent meetings {first} was in:\n{d['key_points']}")
    if voice := _voice(d):
        parts.append(f"Lines {first} said in meetings, newest first:\n{voice}")
    else:
        parts.append(f"There are no transcripts of {first}'s own words on file.")
    parts.append(
        f"Write a portrait of {d['name']} in Markdown, about 250 words at most, in exactly this shape:\n"
        "1. A line \"**How they talk**\", then one or two sentences on their tone and manner, from their own lines if "
        "there are any (say so if there aren't).\n"
        "2. A line \"**What they care about**\", then 2 to 4 short bullets.\n"
        "3. A line \"**How they seem to see you**\", then one or two sentences.\n"
        "4. A line \"**Open threads**\", then 1 to 3 bullets: what's unresolved between you.\n"
        "5. A line \"**What tends to set them off**\", then 1 or 2 bullets, or \"Nothing on file.\"\n"
        "6. A line \"**Not on file**\", then 1 to 3 bullets: what a conversation might touch that the records don't cover.\n"
        "Nothing else: no title, no preamble, no sign-off.")
    return "\n\n".join(parts)


def write_portrait(job: jobs.Job) -> None:
    """Writes one person's portrait, unless the one on file was written from these same records."""
    try:
        d = _dossier(job.target)
    except (LookupError, SedimentError):
        return
    fp = fingerprint(d)
    row = store.portrait(d["ref"])
    if (row and row["fingerprint"] == fp) or not d["material"]:
        return
    job.stage("Writing the portrait")
    try:
        body, pid = ai.complete(portrait_prompt(d), PORTRAIT_SYSTEM, choice(), purpose="Sediment portraits")
    except ai.AIError as e:
        if e.provider_down:
            raise jobs.Wait(str(e)) from e
        raise
    store.save_portrait(d["ref"], body.strip(), fp, readings.written_by(pid))
    _changed(d["ref"])


# ── Conversations ─────────────────────────────────────────────────────

def _with_jobs(msgs: list[dict]) -> list[dict]:
    work = jobs.latest("sediment", [m["id"] for m in msgs if m["status"] == "queued"])
    return [{**m, "job": work.get(m["id"])} for m in msgs]


def conversations(person_ref: str) -> list[dict]:
    return store.conversations_of(person_ref)


def start(person_ref: str, scenario: str) -> dict:
    scenario = (scenario or "").strip()
    if len(scenario) > MAX_SCENARIO:
        raise SedimentError(f"Keep the scenario under {MAX_SCENARIO} characters")
    d = _dossier(person_ref)
    cid = store.add_conversation(d["ref"], d["name"], scenario)
    _changed(d["ref"])
    return conversation(cid)


def conversation(conversation_id: str) -> dict:
    c = store.conversation(conversation_id)
    if not c:
        raise LookupError("That conversation is gone")
    return {**c, "messages": _with_jobs(store.messages(conversation_id))}


def say(conversation_id: str, text: str) -> dict:
    c = store.conversation(conversation_id)
    if not c:
        raise LookupError("That conversation is gone")
    text = (text or "").strip()
    if not text:
        raise SedimentError("Type something first")
    if len(text) > MAX_LINE:
        raise SedimentError(f"Keep it under {MAX_LINE:,} characters")
    if any(m["status"] == "queued" for m in store.messages(conversation_id)):
        raise SedimentError("A reply is still on its way")
    store.add_message(conversation_id, "you", text)
    mid = store.add_message(conversation_id, "them", status="queued")
    jobs.enqueue("sediment", "reply", mid)
    _changed(c["person_ref"])
    return conversation(conversation_id)


def retry(message_id: str) -> dict:
    m = store.message(message_id)
    if not m or m["role"] != "them":
        raise SedimentError("That reply is gone")
    store.requeue_message(message_id)
    jobs.enqueue("sediment", "reply", message_id)
    c = store.conversation(m["conversation_id"])
    _changed(c["person_ref"] if c else "")
    return conversation(m["conversation_id"])


def delete(conversation_id: str) -> None:
    c = store.conversation(conversation_id)
    for mid in store.delete_conversation(conversation_id):
        jobs.cancel_for("sediment", mid)
    if c:
        _changed(c["person_ref"])


def reply_prompt(d: dict, portrait: dict | None, scenario: str, history: list[dict], left_out: int) -> str:
    first = d["first"]
    parts = [f"{d['owner']} Today is {_today()}."]
    if scenario:
        parts.append(f"The scene the owner wants to rehearse: {scenario}")
    parts.append(f"Portrait of {first}:\n{portrait['body']}" if portrait else f"No portrait of {first} has been written yet.")
    parts.append(f"Records about {d['name']}:\n\n{d['records']}")
    if voice := _voice(d):
        parts.append(f"Lines {first} said in meetings, newest first (how they really talk):\n{voice}")
    lines = [f"{'You' if m['role'] == 'you' else first}: {m['body']}" for m in history]
    talk = "\n".join(lines)
    parts.append("The conversation so far (\"You\" is the owner)"
                 + (f", the earliest {left_out} lines left out" if left_out else "") + f":\n{talk}")
    parts.append(f"Reply as {first} to the owner's last line.")
    return "\n\n".join(parts)


def _spans(reply: str, phrases: list[str]) -> list[str]:
    """Each phrase as it's written in the reply (found ignoring case), dropping any that aren't in it."""
    out, low = [], reply.lower()
    for p in phrases:
        p = p.strip().strip("“”\"")
        at = low.find(p.lower()) if p else -1
        if at >= 0 and reply[at:at + len(p)] not in out:
            out.append(reply[at:at + len(p)])
    return out


def reply(job: jobs.Job) -> None:
    """Writes their next line. A failure stays on the line with Try again; an AI that can't answer for now waits."""
    m = store.message(job.target)
    if not m or m["status"] == "done":
        return
    c = store.conversation(m["conversation_id"])
    if not c:
        return

    def fail(text: str) -> None:
        store.fail_message(m["id"], text)
        _changed(c["person_ref"])

    prov = provider()
    if not prov["ready"]:
        return fail(prov["reason"] or "No AI is set up for this yet (Settings → AI)")
    try:
        d = _dossier(c["person_ref"])
    except LookupError:
        return fail("They're no longer in your book")
    except SedimentError as e:
        return fail(str(e))
    done = [x for x in store.messages(c["id"]) if x["status"] == "done" and x["created_at"] <= m["created_at"]]
    history = done[-HISTORY:]
    job.stage("Writing a reply")
    try:
        answer, pid = ai.structured(reply_prompt(d, store.portrait(d["ref"]), c["scenario"], history, len(done) - len(history)),
                                    reply_system(d["name"], d["first"]), Reply, choice(), purpose="Sediment rehearsals")
    except ai.AIError as e:
        if e.provider_down:
            raise jobs.Wait(str(e)) from e
        return fail(str(e))
    text = answer.reply.strip()  # type: ignore[attr-defined]
    if not text:
        return fail("The reply came back empty")
    guesses = _spans(text, answer.guesses)  # type: ignore[attr-defined]
    grounds = [{"phrase": span, "source": g.source.strip()} for g in answer.grounds  # type: ignore[attr-defined]
               for span in _spans(text, [g.phrase]) if g.source.strip()]
    store.finish_message(m["id"], text, guesses, grounds, readings.written_by(pid))
    _changed(c["person_ref"])
