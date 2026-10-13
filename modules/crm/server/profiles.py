"""AI overviews of people, and questions you ask about them.

Everyone but you gets a short overview written from what's on file: who they are, how you know them, what's worth
knowing, and a reason to get back in touch. Overviews are written ahead of time in the background, the people
closest to you first and a few at a time, and written again when what's on file about someone changes (the
overview keeps a fingerprint of the records it was written from). Opening a profile that has none yet, or an
out-of-date one, asks for it straight away, ahead of the background work.

You can also ask about a person. Each question and its answer are kept on their profile, and the last few go along
with the next question so follow-ups make sense.

Which AI does this is the "profiles" job in Settings → AI (crm.profiles_provider). The default is "Same as the
app", which is the local model unless a cloud provider was chosen there. The model is given records from this app
only, and told to use nothing else.

    crm_overviews   one per person: the text, who wrote it, and the fingerprint of what it was written from
    crm_questions   what you asked about someone, the answer, and whether it's still being worked on
(the tables are created in store.py, with the module's other tables)
"""
import hashlib
from datetime import UTC, date, datetime

from core.server import ai, db, events, jobs, settings

from . import roles, store, views
from .connections import sort_key
from .model import Entity, iso

PROMPT_VERSION = "1"            # change it to have every overview written again after changing the prompt
SWEEP_SECONDS = 600
PER_SWEEP = {"local": 4, "cloud": 25}
BUDGET = {"local": 24_000, "cloud": 120_000}   # characters of records given to the model
NOTE_CAP = {"local": 6_000, "cloud": 30_000}   # the most of any one note
MEETINGS, DOCUMENTS, PEOPLE, MUTUAL = 25, 12, 25, 12
HISTORY = 6                     # earlier questions sent along with a new one
MAX_QUESTION = 2_000
OVERVIEW_KINDS = ("overview", "overview_now")

TIER_WORDS = {
    "strong": "a strong connection (close and trusted)",
    "working": "a working relationship (people you actively work with)",
    "light": "a light connection (you've met or been in touch)",
    "indirect": "an indirect connection (they came up through others)",
    "none": "not linked to you yet",
}

OVERVIEW_SYSTEM = (
    "You write short briefings about people for the owner of a personal CRM, from the owner's own records. "
    "Write plain, warm English and address the owner as \"you\". Use only facts in the records. Never invent or "
    "guess, and add nothing from general knowledge, even about well-known people. If the records say little, "
    "say so in a sentence."
)
ANSWER_SYSTEM = (
    "You answer questions about one person for the owner of a personal CRM, using only the owner's records "
    "below. Address the owner as \"you\". Be brief and direct: a few sentences or a short list. If the records "
    "don't answer the question, say so plainly, and say what is on file that comes closest. Never invent facts "
    "or add general knowledge."
)


class ProfileError(ValueError):
    pass


def _now() -> str:
    return iso(datetime.now(UTC))  # type: ignore[return-value]


def _day(d: date | datetime | None) -> str:
    return d.strftime("%Y-%m-%d") if d else "undated"


def _changed(person_id: str) -> None:
    """Tells open screens to refresh, without moving the store's version (nothing in the graph changed)."""
    events.publish("crm.profile.changed", {"id": person_id})


# ── Which AI ──────────────────────────────────────────────────────────

def choice() -> str:
    return roles.choice("profiles")


def provider() -> dict:
    """The AI that writes overviews and answers, and whether it's ready."""
    return ai.describe(choice())


def _scale(local: bool) -> str:
    return "local" if local else "cloud"


def _written_by(pid: str) -> str:
    cfg = settings.section("ai")
    try:
        return f"{ai.label(pid, cfg)} ({ai.model_for(pid, cfg)})"
    except (KeyError, TypeError):
        return pid


def overview_lane(target: str) -> str:
    return "default" if provider()["local"] else "cloud"


# ── What's on file ────────────────────────────────────────────────────

def _person(v: views.Views, person_id: str) -> Entity:
    p = v.snap.entities.get(person_id)
    if p is None:
        raise LookupError("There's no one with that id")
    if p.kind != "person" or p.is_self:
        raise ProfileError("Overviews and questions are for people other than you")
    return p


def records(v: views.Views, p: Entity, local: bool) -> tuple[str, bool]:
    """Everything on file about a person, as text for the model, and whether there is anything beyond a name.
    Dates are absolute and nothing depends on today, so the text only changes when the records do."""
    a = p.attributes or {}
    ctx = v.context(p.id)
    conn = v.conns.get(p.id)
    org = v.employer(p.id)
    budget, cap = BUDGET[_scale(local)], NOTE_CAP[_scale(local)]
    ents = v.snap.entities
    material = False

    head = [f"Name: {p.name}"]
    if a.get("aliases"):
        head.append("Also written as: " + ", ".join(a["aliases"]))
    if role := " at ".join(x for x in (a.get("title"), org.name if org else None) if x):
        head.append(f"Role: {role}")
        material = True
    for key, label in (("location", "Location"), ("linkedin_url", "LinkedIn"), ("website", "Website"),
                       ("connection_stage", "Stage"), ("last_contact", "Last contact, as you recorded it")):
        if a.get(key):
            head.append(f"{label}: {a[key]}")
    if p.tags:
        head.append("Your tags for them: " + ", ".join(p.tags))

    if ctx.affiliations:
        material = True
        head.append("Organizations:")
        for af in ctx.affiliations:
            for r in af.roles:
                span = f"{_day(r.started_at) if r.started_at else '?'} to {_day(r.ended_at) if r.ended_at else 'now'}"
                when = f", {span}" if r.started_at or r.ended_at else ""
                head.append(f"- {af.org.name}: {r.title or r.label}{when}" + ("" if af.current else " (earlier)"))

    you = ["How they're connected to you:"]
    if conn:
        you.append(f"- {TIER_WORDS.get(conn.tier, conn.tier)}")
        if conn.strength:
            you.append(f"- Your rating of the relationship: {conn.strength} of 5")
        if conn.context:
            you.append(f"- How you know them: {conn.context}")
        if conn.roles:
            you.append(f"- To you they are: {'; '.join(conn.roles)}")
        if conn.meetings:
            you.append(f"- Meetings together: {conn.meetings}, first {_day(conn.first_met_at)}, latest {_day(conn.last_met_at)}")
        if conn.mutual:
            you.append("- People you both know: " + ", ".join(ents[m].name for m in conn.mutual[:MUTUAL] if m in ents))
        if conn.via:
            you.append("- Who brought them up: " + ", ".join(ents[m].name for m in conn.via[:MUTUAL] if m in ents))
        material = material or conn.tier in ("strong", "working", "light") or bool(conn.context or conn.strength)

    parts = ["\n".join(head), "\n".join(you)]
    if (p.summary or "").strip():
        parts.append("Profile summary on file:\n" + p.summary.strip()[:cap])
        material = True

    def room() -> int:
        return budget - sum(len(x) + 2 for x in parts)

    if ctx.meetings:
        material = True
        lines = ["Meetings with or about them, newest first:"]
        for m in ctx.meetings[:MEETINGS]:
            ev = ents.get(m.event.id)
            line = f"- {_day(m.event.occurred_at)}: {m.event.name} ({'you were there' if m.with_me else m.role})"
            if ev and (ev.summary or "").strip():
                line += f"\n  Summary: {ev.summary.strip()[:600]}"
            elif m.snippet:
                line += f"\n  {m.snippet}"
            lines.append(line)
        parts.append("\n".join(lines)[: max(room(), 0)])

    notes = store.notes_of(p.id)
    if notes:
        material = True
        lines = ["Your notes on them, newest first:"]
        shown = 0
        for n in notes:
            left = room() - sum(len(x) + 1 for x in lines) - 200
            if left <= 0:
                break
            body = n.body.strip()[: min(cap, left)]
            lines.append(f"[{_day(n.occurred_at)}, {n.source}] {body}")
            shown += 1
        if shown < len(notes):
            lines.append(f"({len(notes) - shown} older notes left out for length)")
        parts.append("\n".join(lines))

    if ctx.documents and room() > 400:
        material = True
        lines = ["Documents by or about them:"]
        for d in ctx.documents[:DOCUMENTS]:
            ev = ents.get(d.event.id)
            about = f": {ev.summary.strip()[:300]}" if ev and (ev.summary or "").strip() else ""
            lines.append(f"- {_day(d.event.occurred_at)}: {d.event.name} ({d.role}){about}")
        parts.append("\n".join(lines)[: max(room(), 0)])

    if ctx.people and room() > 300:
        lines = ["People they're connected to:"]
        for link in ctx.people[:PEOPLE]:
            lines.append(f"- {link.person.name}: {link.relation}" + (f" ({link.detail})" if link.detail else "")
                         + ("" if link.current else ", earlier"))
        parts.append("\n".join(lines)[: max(room(), 0)])

    return "\n\n".join(x for x in parts if x.strip()), material


def _about_me(v: views.Views) -> str:
    me = v.me
    if not me:
        return ""
    org = v.employer(me.id)
    title = (me.attributes or {}).get("title")
    return f"The owner is {me.name}" + (f", {title}" if title else "") + (f" at {org.name}" if org else "") + "."


def fingerprint(v: views.Views, p: Entity, local: bool) -> tuple[str, str, bool]:
    """(fingerprint, records, material). Changes when the records, the prompt or the AI's size class change."""
    text, material = records(v, p, local)
    seed = "\n".join((PROMPT_VERSION, choice(), _scale(local), _about_me(v), text))
    return hashlib.sha256(seed.encode()).hexdigest()[:24], text, material


# ── Overviews ─────────────────────────────────────────────────────────

def _overview_row(person_id: str) -> dict | None:
    return db.one("SELECT body, fingerprint, written_by, created_at FROM crm_overviews WHERE entity_id = ?", (person_id,))


def _overview_job(person_id: str) -> dict | None:
    return db.one(
        f"SELECT id, kind, status, stage, wait_reason, error, updated_at FROM core_jobs WHERE module = 'crm' "
        f"AND kind IN {OVERVIEW_KINDS} AND target = ? ORDER BY created_at DESC LIMIT 1", (person_id,))


def overview_state(person_id: str) -> dict:
    """The overview as it stands, whether it's current, and the work on it. Asks for a new one straight away if
    there is none or it's out of date, unless the last try failed (that shows, with Try again)."""
    v = views.get()
    p = _person(v, person_id)
    prov = provider()
    fp, _, material = fingerprint(v, p, prov["local"])
    row = _overview_row(p.id)
    job = _overview_job(p.id)
    current = bool(row and row["fingerprint"] == fp)
    unfinished = job and job["status"] in jobs.UNFINISHED
    if prov["ready"] and material and not current and not unfinished and not (job and job["status"] == "error"):
        jobs.enqueue("crm", "overview_now", p.id)
        job = _overview_job(p.id)
    return {
        "overview": {"body": row["body"], "written_by": row["written_by"], "created_at": row["created_at"], "current": current} if row else None,
        "job": job, "material": material,
        "ready": prov["ready"], "reason": prov["reason"], "provider": prov["label"], "local": prov["local"],
    }


def redo_overview(person_id: str) -> dict:
    v = views.get()
    p = _person(v, person_id)
    db.execute("UPDATE crm_overviews SET fingerprint = '' WHERE entity_id = ?", (p.id,))
    jobs.enqueue("crm", "overview_now", p.id)
    _changed(p.id)
    return overview_state(p.id)


def write_overview(job: jobs.Job) -> None:
    """Writes one person's overview, unless the one on file was written from these same records."""
    v = views.get()
    p = v.snap.entities.get(job.target)
    if p is None or p.kind != "person" or p.is_self:
        return
    prov = provider()
    fp, text, material = fingerprint(v, p, prov["local"])
    row = _overview_row(p.id)
    if row and row["fingerprint"] == fp:
        return
    if not material:
        return
    job.stage("Writing the overview")
    prompt = (
        f"{_about_me(v)}\n\nRecords about {p.name}:\n\n{text}\n\n"
        f"Write an overview of {p.name} in Markdown, about 170 words at most, in exactly this shape:\n"
        f"1. One or two opening sentences, no heading: who {p.name} is and how you know them.\n"
        "2. A line \"**Worth knowing**\", then 2 to 4 short bullets with the most useful facts from the records "
        "(their work, interests, what you've done together, anything left open).\n"
        "3. A line \"**Next time**\", then one sentence with a concrete reason or topic for getting back in touch, "
        "drawn from the records.\n"
        "Nothing else: no title, no preamble, no sign-off."
    )
    try:
        body, pid = ai.complete(prompt, OVERVIEW_SYSTEM, choice())
    except ai.AIError as e:
        if e.provider_down:
            raise jobs.Wait(str(e)) from e
        raise
    now = _now()
    db.execute(
        "INSERT INTO crm_overviews (id, entity_id, body, fingerprint, written_by, created_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(entity_id) DO UPDATE SET body = excluded.body, fingerprint = excluded.fingerprint, "
        "written_by = excluded.written_by, created_at = excluded.created_at",
        (db.new_id(), p.id, body.strip(), fp, _written_by(pid), now),
    )
    _changed(p.id)


def sweep_seconds() -> int:
    return SWEEP_SECONDS if settings.section("crm")["overviews_ahead"] else 0


def sweep(job: jobs.Job) -> None:
    """Queues overviews for the people who have none or an out-of-date one, closest first, a few per run so the
    machine (or the bill) isn't swamped. Nothing while the AI isn't set up, or while earlier ones wait on it."""
    if not settings.section("crm")["overviews_ahead"]:
        return
    prov = provider()
    if not prov["ready"]:
        return
    if db.one(f"SELECT 1 AS x FROM core_jobs WHERE module = 'crm' AND kind IN {OVERVIEW_KINDS} AND status IN ('waiting', 'queued', 'running')"):
        return  # the last batch is still going, or is parked until the AI works again
    v = views.get()
    have = {r["entity_id"]: r["fingerprint"] for r in db.query("SELECT entity_id, fingerprint FROM crm_overviews")}
    failed = {r["target"] for r in db.query(
        f"SELECT target FROM core_jobs WHERE module = 'crm' AND kind IN {OVERVIEW_KINDS} AND status = 'error'")}
    people = [p for p in v.snap.of_kind("person") if not p.is_self and p.id in v.conns and p.id not in failed]
    people.sort(key=lambda p: sort_key(v.conns[p.id], p.name))
    limit, queued = PER_SWEEP[_scale(prov["local"])], 0
    for p in people:
        fp, _, material = fingerprint(v, p, prov["local"])
        if material and have.get(p.id) != fp:
            jobs.enqueue("crm", "overview", p.id)
            queued += 1
            if queued >= limit:
                break
    if queued:
        job.stage(f"Queued {queued} overview{'s' if queued != 1 else ''}")


def coverage() -> dict:
    """How many of your people have an overview, for Settings."""
    v = views.get()
    ids = [p.id for p in v.snap.of_kind("person") if not p.is_self and p.id in v.conns]
    have = {r["entity_id"] for r in db.query("SELECT entity_id FROM crm_overviews")}
    return {"people": len(ids), "written": sum(1 for i in ids if i in have)}


# ── Questions ─────────────────────────────────────────────────────────

def _question(row: dict) -> dict:
    return {k: row[k] for k in ("id", "question", "answer", "status", "error", "written_by", "created_at", "answered_at")}


def questions(person_id: str) -> list[dict]:
    _person(views.get(), person_id)
    return [_question(r) for r in db.query("SELECT * FROM crm_questions WHERE entity_id = ? ORDER BY created_at, id", (person_id,))]


def ask(person_id: str, question: str) -> dict:
    p = _person(views.get(), person_id)
    question = (question or "").strip()
    if not question:
        raise ProfileError("Type a question first")
    if len(question) > MAX_QUESTION:
        raise ProfileError(f"Keep the question under {MAX_QUESTION:,} characters")
    qid = db.new_id()
    db.execute("INSERT INTO crm_questions (id, entity_id, question, status, created_at) VALUES (?, ?, ?, 'queued', ?)",
               (qid, p.id, question, _now()))
    jobs.enqueue("crm", "answer", qid)
    _changed(p.id)
    return _question(db.one("SELECT * FROM crm_questions WHERE id = ?", (qid,)))


def retry(question_id: str) -> dict:
    row = db.one("SELECT * FROM crm_questions WHERE id = ?", (question_id,))
    if not row:
        raise ProfileError("That question is gone")
    db.execute("UPDATE crm_questions SET status = 'queued', error = NULL WHERE id = ?", (question_id,))
    jobs.enqueue("crm", "answer", question_id)
    _changed(row["entity_id"])
    return _question(db.one("SELECT * FROM crm_questions WHERE id = ?", (question_id,)))


def clear(person_id: str) -> None:
    _person(views.get(), person_id)
    for row in db.query("SELECT id FROM crm_questions WHERE entity_id = ?", (person_id,)):
        jobs.cancel_for("crm", row["id"])
    db.execute("DELETE FROM crm_questions WHERE entity_id = ?", (person_id,))
    _changed(person_id)


def answer(job: jobs.Job) -> None:
    """Answers one question from the person's records, their overview and the conversation so far."""
    row = db.one("SELECT * FROM crm_questions WHERE id = ?", (job.target,))
    if not row or row["status"] == "done":
        return
    v = views.get()
    p = v.snap.entities.get(row["entity_id"])
    if p is None:
        return

    def fail(text: str) -> None:
        db.execute("UPDATE crm_questions SET status = 'error', error = ? WHERE id = ?", (text, row["id"]))
        _changed(row["entity_id"])

    prov = provider()
    if not prov["ready"]:
        return fail(prov["reason"] or "No AI is set up for this yet (Settings → AI)")
    _, text, _ = fingerprint(v, p, prov["local"])
    overview = _overview_row(p.id)
    earlier = db.query(
        "SELECT question, answer FROM crm_questions WHERE entity_id = ? AND status = 'done' AND created_at <= ? AND id != ? "
        "ORDER BY created_at DESC LIMIT ?", (p.id, row["created_at"], row["id"], HISTORY))
    talk = "\n\n".join(f"You asked: {r['question']}\nAnswer: {r['answer']}" for r in reversed(earlier))
    prompt = (
        f"{_about_me(v)} Today is {datetime.now(UTC).strftime('%A %d %B %Y')}.\n\n"
        f"Records about {p.name}:\n\n{text}\n\n"
        + (f"The overview already written about them:\n{overview['body']}\n\n" if overview else "")
        + (f"Earlier in this conversation:\n{talk}\n\n" if talk else "")
        + f"Question: {row['question']}"
    )
    job.stage("Thinking")
    try:
        reply, pid = ai.complete(prompt, ANSWER_SYSTEM, choice())
    except ai.AIError as e:
        return fail(str(e))
    db.execute("UPDATE crm_questions SET status = 'done', answer = ?, error = NULL, written_by = ?, answered_at = ? WHERE id = ?",
               (reply.strip(), _written_by(pid), _now(), row["id"]))
    _changed(row["entity_id"])
