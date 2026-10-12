"""The inbox API, mounted under /api/crm/ingest: add notes and files, see what the AI proposed, apply or discard it."""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from core.server import jobs, settings

from . import ingest, inbox, linkedin

router = APIRouter(prefix="/ingest")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_BATCH_BYTES = 200 * 1024 * 1024


class NoteIn(BaseModel):
    text: str = Field(min_length=1)
    title: str | None = None
    occurred_at: datetime | None = None


class ApplyIn(BaseModel):
    proposal: dict[str, Any]


class AttendeeIn(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    email: str | None = Field(default=None, max_length=300)
    is_self: bool = False   # the owner, when the recorder marks them


class MeetingIn(BaseModel):
    """A recorded meeting from a transcript tool (Granola, a calendar sync, …)."""
    origin: str = Field(default="granola", min_length=1, max_length=32, pattern=r"^[\w.-]+$")
    external_id: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=300)
    started_at: datetime | None = None
    attendees: list[AttendeeIn] = Field(default_factory=list, max_length=200)
    notes: str | None = None        # the recorder's own notes or summary
    transcript: str | None = None
    auto_apply: bool = True


def _work(rows: list[dict]) -> dict[str, dict]:
    return jobs.latest("crm", [r["id"] for r in rows])


def _detail(row: dict) -> dict:
    return {**row, "work": _work([row]).get(row["id"])}


def _get(row_id: str) -> dict:
    try:
        return inbox.require(row_id)
    except inbox.NotFound as e:
        raise HTTPException(404, str(e)) from e


@router.post("/notes", status_code=202)
def add_note(body: NoteIn):
    """Paste meeting notes; they're read in the background, then wait for your review."""
    return _detail(ingest.create_note_job(body.text, body.title, body.occurred_at.isoformat() if body.occurred_at else None))


@router.post("/files", status_code=202)
def add_files(files: list[UploadFile] = File(...), auto_apply: bool = Form(True)):
    """Documents (.docx .pdf .pptx .txt .md). A file name may carry a folder ("Clients/Acme/notes.docx"): folders and
    neighbouring file names give the AI useful context."""
    blobs: list[tuple[str, bytes]] = []
    total = 0
    for f in files:
        data = f.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{f.filename} is larger than 20 MB")
        total += len(data)
        if total > MAX_BATCH_BYTES:
            raise HTTPException(413, "That's more than 200 MB; add it in smaller batches")
        blobs.append(((f.filename or "untitled").lstrip("/"), data))
    rows = ingest.create_file_jobs(blobs, auto_apply=auto_apply)
    work = _work(rows)
    return [{k: v for k, v in r.items() if k not in ("raw_text", "proposal")}
            | {"filename": r["payload"].get("filename"), "work": work.get(r["id"])} for r in rows]


@router.get("/jobs")
def list_jobs(status: str | None = None, limit: int = 100):
    rows = inbox.listing(status.split(",") if status else None, limit)
    work = _work(rows)
    return [{**r, "work": work.get(r["id"])} for r in rows]


@router.get("/summary")
def summary():
    counts = inbox.counts()
    parked = jobs.waiting("crm", "extract")
    reason = None
    if parked:
        from core.server import db
        row = db.one("SELECT wait_reason FROM core_jobs WHERE id = ?", (parked[0],))
        reason = row["wait_reason"] if row else None
    return {"counts": counts, "active": counts.get("pending", 0) + counts.get("processing", 0),
            "parked": {"count": len(parked), "reason": reason}}


@router.post("/jobs/apply-ready")
def apply_ready():
    """Apply everything awaiting review whose matches are unambiguous (and wasn't read by rules alone)."""
    return ingest.apply_ready()


@router.post("/resume")
def resume():
    """Carry on after fixing the AI provider: everything parked for it goes again."""
    return {"resumed": ingest.resume()}


@router.get("/jobs/{row_id}")
def get_job(row_id: str):
    return _detail(_get(row_id))


@router.post("/jobs/{row_id}/apply")
def apply_job(row_id: str, body: ApplyIn):
    _get(row_id)
    try:
        ingest.apply_proposal(row_id, body.proposal)
    except ingest.ProposalError as e:
        raise HTTPException(422, str(e)) from e
    return _detail(_get(row_id))


@router.post("/jobs/{row_id}/discard")
def discard_job(row_id: str):
    _get(row_id)
    try:
        return _detail(ingest.discard(row_id))
    except ingest.ProposalError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/jobs/{row_id}/retry", status_code=202)
def retry_job(row_id: str):
    _get(row_id)
    try:
        return _detail(ingest.retry(row_id))
    except ingest.ProposalError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/linkedin", status_code=201)
def add_linkedin(file: UploadFile = File(...)):
    """Connections.csv from LinkedIn's own data export. Running it again adds nothing twice."""
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That file is larger than 20 MB")
    try:
        rows = linkedin.parse_connections_csv(raw.decode("utf-8-sig", errors="replace"))
    except linkedin.LinkedInFormatError as e:
        raise HTTPException(422, str(e)) from e
    if not rows:
        raise HTTPException(422, "No connections found in the file")
    return linkedin.import_connections(rows, file.filename)


@router.post("/meeting", status_code=202)
def add_meeting(body: MeetingIn, response: Response):
    """A recorded meeting: title, start, invitees with emails, the recorder's notes and/or the transcript. Your
    extraction model writes the notes. Safe to resend: a meeting already in returns its earlier item with 200
    instead of queuing a duplicate."""
    try:
        row, seen = ingest.create_meeting_job(
            origin=body.origin, external_id=body.external_id, title=body.title,
            started_at=body.started_at.isoformat() if body.started_at else None,
            attendees=[a.model_dump() for a in body.attendees], notes=body.notes, transcript=body.transcript,
            auto_apply=body.auto_apply)
    except ingest.ProposalError as e:
        raise HTTPException(422, str(e)) from e
    if seen:
        response.status_code = 200
    return _detail(row)


def _pick(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", []):
            return value
    return None


def _attendee_names(value: Any) -> list[str]:
    out = []
    for a in value if isinstance(value, list) else []:
        if isinstance(a, str):
            out.append(a)
        elif isinstance(a, dict):
            name = a.get("name") or a.get("displayName") or a.get("display_name")
            email = a.get("email")
            if name and email:
                out.append(f"{name} <{email}>")
            elif name or email:
                out.append(name or email)
    return out


@router.post("/webhook", status_code=202)
def add_webhook(payload: dict[str, Any]):
    """Meeting notes from Zapier, n8n, Make or a note-taking app. Accepts JSON with any of text, notes, transcript,
    summary or content; title; date, occurred_at or start_time; attendees or participants (names, or {name, email}).
    A top-level "data" object is unwrapped. It's only reachable from other machines when the app runs as a server,
    where it needs the access token like everything else (Authorization: Bearer …)."""
    data = {**payload, **payload["data"]} if isinstance(payload.get("data"), dict) else payload
    text = _pick(data, "text", "notes", "transcript", "summary", "content", "body", "markdown")
    if isinstance(text, list):
        text = "\n".join(str(t) for t in text)
    if not text or not str(text).strip():
        raise HTTPException(422, "The payload has no notes text (expected text, notes, transcript, summary or content)")
    names = _attendee_names(_pick(data, "attendees", "participants", "invitees"))
    if names:
        text = f"Attendees: {', '.join(names)}\n\n{text}"
    when = ingest.parse_dt(str(_pick(data, "occurred_at", "date", "start_time", "started_at", "meeting_date") or ""))
    row = inbox.create("webhook", title=_pick(data, "title", "meeting_title", "subject", "name"),
                       occurred_at=when.isoformat() if when else None, raw_text=str(text),
                       payload={**payload, "auto_apply": bool(settings.section("crm")["webhook_auto_apply"])})
    ingest.queue([row["id"]])
    return _detail(row)
