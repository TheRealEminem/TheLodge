"""The notes API, mounted at /api/notes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.server import contracts, events, jobs, links, settings

from . import store

router = APIRouter()


class NoteIn(BaseModel):
    title: str = ""
    body: str = ""


class NotePatch(BaseModel):
    title: str | None = None
    body: str | None = None


def _get_or_404(note_id: str) -> dict:
    note = store.get(note_id)
    if not note:
        raise HTTPException(404, "Note not found")
    return note


def _queue_summary(note_id: str) -> None:
    """After a save: summarize now if that's automatic, otherwise park it as "Needs you"."""
    auto = settings.section("notes")["auto_summarize"]
    jobs.enqueue("notes", "summarize", note_id, approve=not auto)


@router.get("")
def list_notes():
    notes = store.all_notes()
    state = jobs.latest("notes", [n["id"] for n in notes])
    return [{**n, "job": state.get(n["id"])} for n in notes]


@router.post("", status_code=201)
def create_note(body: NoteIn):
    note_id = store.create(body.title.strip() or "Untitled note", body.body)
    events.publish("notes.note.saved", {"id": note_id})
    if body.body.strip():
        _queue_summary(note_id)
    return {"id": note_id}


@router.get("/{note_id}")
def get_note(note_id: str):
    note = _get_or_404(note_id)
    return {**note, "job": jobs.latest("notes", [note_id]).get(note_id),
            "links": links.linked(links.ref("notes", note_id))}


@router.patch("/{note_id}")
def patch_note(note_id: str, body: NotePatch):
    note = _get_or_404(note_id)
    changes = body.model_dump(exclude_none=True)
    if "title" in changes:
        changes["title"] = changes["title"].strip() or "Untitled note"
    store.update(note_id, **changes)
    events.publish("notes.note.saved", {"id": note_id})
    if "body" in changes and changes["body"].strip() and changes["body"] != note["body"]:
        _queue_summary(note_id)
    return {"ok": True}


@router.post("/{note_id}/summarize", status_code=202)
def summarize_now(note_id: str):
    _get_or_404(note_id)
    jobs.enqueue("notes", "summarize", note_id)
    return {"ok": True}


@router.delete("/{note_id}", status_code=204)
def delete_note(note_id: str):
    _get_or_404(note_id)
    ref = links.ref("notes", note_id)
    jobs.cancel_for("notes", note_id)
    store.delete(note_id)
    events.publish(contracts.ITEM_DELETED, {"ref": ref})
    links.forget(ref)
