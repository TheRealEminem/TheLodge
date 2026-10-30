"""The Sediment API, mounted at /api/sediment. A person is named by their ref in the People module, "crm:<id>"."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from core.server import contracts, events, jobs, module, settings

from . import readings, store, talk

router = APIRouter()
ME = "core:me"


class ReadingIn(BaseModel):
    subject: str
    again: bool = False


class SubjectIn(BaseModel):
    kind: Literal["product", "person", "organization"]
    name: str = ""
    ref: str | None = None
    description: str = ""
    terms: list[str] = []


class ConversationIn(BaseModel):
    scenario: str = ""


class LineIn(BaseModel):
    text: str


class SubjectEdit(BaseModel):
    name: str
    description: str = ""
    terms: list[str] = []


def _guard(fn, *args):
    try:
        return fn(*args)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except readings.SedimentError as e:
        raise HTTPException(422, str(e)) from e


def _person_ref(ref: str) -> str:
    if ref == ME:
        raise readings.SedimentError("Sediment reads other people: choose someone other than you")
    return ref


def _terms(terms: list[str]) -> list[str]:
    return [t.strip() for t in terms if t.strip()][:12]


def _provider() -> dict:
    p = readings.provider()
    return {"label": p["label"], "model": p["model"], "ready": p["ready"], "reason": p["reason"], "local": p["local"]}


def _page(ref: str) -> dict:
    prov = readings.provider()
    try:
        d = readings.dossier(_person_ref(ref), None, prov["local"])
    except LookupError:
        kept = store.readings_of(ref)
        return {"missing": True, "person": {"ref": ref, "name": kept[0]["person_name"] if kept else None},
                "subjects": [], "readings": kept, "provider": _provider()}
    if d["ref"] != ref:  # merged into someone else since: their readings follow
        store.repoint(ref, d["ref"])
    company = d.get("company")
    subjects = [{"key": "me", "name": "You", "kind": "me"}]
    if company:
        subjects.append({"key": "company", "name": company["name"], "kind": "company"})
    for s in store.subjects():
        if s["ref"] in (d["ref"], (company or {}).get("ref")):
            continue
        subjects.append({"key": s["key"], "id": s["id"], "name": s["name"], "kind": s["kind"],
                         "description": s["description"], "terms": s["terms"]})
    kept = store.readings_of(d["ref"])
    work = jobs.latest("sediment", [r["id"] for r in kept if r["status"] == "queued"])
    for r in kept:
        r["job"] = work.get(r["id"])
    return {"missing": False,
            "person": {"ref": d["ref"], "name": d["name"], "first": d["first"], "material": d["material"],
                       "meetings_with_you": d["meetings_with_you"]},
            "subjects": subjects, "readings": kept, "provider": _provider(),
            "transcripts": bool(settings.section("sediment")["transcripts"])}


@router.get("/people/{ref}")
def person(ref: str):
    """Everything the person's page shows: who they are, what can be read, and the readings so far."""
    return _guard(_page, ref)


@router.post("/people/{ref}/readings", status_code=201)
def take_reading(ref: str, body: ReadingIn):
    """Read how they feel about a subject. With nothing new on file since the last reading of it, says so instead
    (unless `again`)."""
    return _guard(lambda: readings.request(_person_ref(ref), body.subject, body.again))


@router.delete("/people/{ref}", status_code=204)
def forget_person(ref: str):
    """Everything Sediment holds about someone: readings, portrait and rehearsals. People isn't touched."""
    for rid in store.delete_person(ref):
        jobs.cancel_for("sediment", rid)
    jobs.cancel_for("sediment", ref)
    events.publish("sediment.reading.changed", {"person": ref})
    return Response(status_code=204)


@router.get("/people/{ref}/portrait")
def portrait(ref: str):
    """Their portrait, whether it's up to date, and the work on it. A missing or out-of-date one is asked for."""
    return _guard(lambda: talk.portrait_state(_person_ref(ref)))


@router.post("/people/{ref}/portrait")
def redo_portrait(ref: str):
    return _guard(lambda: talk.redo_portrait(_person_ref(ref)))


@router.get("/people/{ref}/conversations")
def conversations(ref: str):
    return talk.conversations(ref)


@router.post("/people/{ref}/conversations", status_code=201)
def start_conversation(ref: str, body: ConversationIn):
    """A new rehearsal with them, with an optional scene ("I'm asking for an intro to their CFO")."""
    return _guard(lambda: talk.start(_person_ref(ref), body.scenario))


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: str):
    return _guard(talk.conversation, conversation_id)


@router.post("/conversations/{conversation_id}/lines", status_code=201)
def say(conversation_id: str, body: LineIn):
    """Your next line. Their reply is written in the background and appears on the conversation."""
    return _guard(talk.say, conversation_id, body.text)


@router.post("/lines/{message_id}/retry")
def retry_line(message_id: str):
    return _guard(talk.retry, message_id)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str):
    talk.delete(conversation_id)
    return Response(status_code=204)


@router.post("/readings/{reading_id}/retry")
def retry(reading_id: str):
    return _guard(readings.retry, reading_id)


@router.delete("/readings/{reading_id}", status_code=204)
def delete_reading(reading_id: str):
    row = store.reading(reading_id)
    if not row:
        raise HTTPException(404, "That reading is gone")
    jobs.cancel_for("sediment", reading_id)
    store.delete_reading(reading_id)
    events.publish(contracts.ITEM_DELETED, {"ref": f"sediment:{reading_id}"})
    events.publish("sediment.reading.changed", {"person": row["person_ref"]})
    return Response(status_code=204)


@router.get("/recent")
def recent():
    """The latest readings, across everyone, for the page you land on."""
    return store.recent()


@router.get("/subjects")
def subjects():
    return store.subjects()


@router.post("/subjects", status_code=201)
def add_subject(body: SubjectIn):
    if body.kind == "product":
        name = body.name.strip()
        if not name:
            raise HTTPException(422, "Give the product a name")
        out = store.add_subject("product", name[:200], description=body.description.strip()[:2_000], terms=_terms(body.terms))
    else:
        ref = (body.ref or "").strip()
        if not ref.startswith("crm:"):
            raise HTTPException(422, "Choose someone or something from your book")
        if existing := store.subject_by_ref(ref):
            return existing
        found = module.describe(ref)
        if not found:
            raise HTTPException(404, "That isn't in your book any more")
        out = store.add_subject(body.kind, found["title"], ref=ref)
    events.publish("sediment.subjects.changed", {})
    return out


@router.patch("/subjects/{subject_id}")
def edit_subject(subject_id: str, body: SubjectEdit):
    s = store.subject(subject_id)
    if not s:
        raise HTTPException(404, "That subject is gone")
    name = body.name.strip() if s["kind"] == "product" else s["name"]
    if not name:
        raise HTTPException(422, "Give the product a name")
    store.update_subject(subject_id, name[:200], body.description.strip()[:2_000], _terms(body.terms))
    events.publish("sediment.subjects.changed", {})
    return store.subject(subject_id)


@router.delete("/subjects/{subject_id}", status_code=204)
def delete_subject(subject_id: str):
    store.delete_subject(subject_id)
    events.publish("sediment.subjects.changed", {})
    return Response(status_code=204)


@router.get("/ai")
def ai_jobs():
    """Who takes readings and who plays people in rehearsals, for Settings → Sediment."""
    t = talk.provider()
    return {"readings": {"choice": settings.section("sediment")["reading_provider"], **_provider()},
            "talk": {"choice": settings.section("sediment")["talk_provider"], "label": t["label"], "model": t["model"],
                     "ready": t["ready"], "reason": t["reason"], "local": t["local"]}}
