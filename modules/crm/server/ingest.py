"""Ingestion: a note, document or recorded meeting -> (triage) -> extraction -> proposal -> (review) -> graph.

Extraction never writes to the graph. It produces a *proposal*, kept on the inbox row. You (or auto-apply, when
nothing is in doubt) apply it in one transaction.

Rules that cost a debugging round in DynaCRM and are pinned by tests:
  - A provider-wide failure (no credit, a bad key or model, rate limit, unreachable) stops the work: the item goes
    back in line, the batch parks with the reason, and "Resume" carries on. It never quietly turns into rules.
  - Only a content failure (refusal, out of output space, wrong shape) falls back to rules, with a warning, and
    such a result is never applied automatically.
  - A name that matches several records is never linked automatically.
  - What you discarded, and what's already in, is skipped when the same content comes in again.
  - Applying is serialized and re-checks for an exact match when it creates, so two documents that mention the same
    new person don't make two people.
"""
import logging
import os
import re
import threading
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import PurePosixPath

from dateutil import parser as dateparser

from core.server import ai, contracts, db, events, jobs

from . import inbox, research, resolve, roles, snapshot, spreadsheets, store, views
from .documents import ParsedSheet, UnsupportedFile, kind_of, parse_document, parse_spreadsheet, text_hash
from .extraction import (EXTRACTION_SYSTEM, TRIAGE_SYSTEM, DocContext, ExtractedEntity, Extraction, Triage, extract_heuristic,
                         extraction_prompt, triage_prompt)
from .kinds import validate_relationship
from .model import iso, parse_dt as parse_iso
from .summaries import subtitle_for

log = logging.getLogger("crm.ingest")

RECORD_REF = "record"
PROFILE_TYPES = ("person_profile", "organization_profile")
BRIEF_MAX_CHARS = 40_000
MAX_MEETING_CHARS = 600_000
MATCH_THRESHOLD = 0.6
FALLBACK_WARNING_PREFIX = "AI extraction failed"
BREAKER_SECONDS = 60

_apply_lock = inbox.write_lock   # writes to the graph one at a time


class ProposalError(ValueError):
    pass


class ProviderDown(RuntimeError):
    """The AI provider can't serve any request right now (credit, key, outage). The batch should stop."""


# ── When the AI provider is down ──────────────────────────────────────

_down: dict = {}   # {"reason": str, "until": monotonic time}: stops the rest of a batch from hammering a dead provider


def _trip(reason: str) -> None:
    _down.update(reason=reason, until=time.monotonic() + BREAKER_SECONDS)


def _breaker() -> str | None:
    if _down and time.monotonic() < _down.get("until", 0):
        return _down["reason"]
    _down.clear()
    return None


def resume() -> int:
    """Carry on after you've fixed the provider (topped up, changed the key or the model). Returns how many resumed."""
    _down.clear()
    waiting = jobs.waiting("crm", "extract")
    for job_id in waiting:
        jobs.go(job_id, force=True)
    return len(waiting)


def on_settings_changed(payload: dict) -> None:
    """Changing the AI settings is usually the fix, so anything parked for the provider goes again."""
    if any(str(k).startswith(("ai.", "crm.")) for k in payload.get("keys", [])) and (_down or jobs.waiting("crm", "extract")):
        resume()


def lane(target: str) -> str:
    """Cloud models can be asked four at a time; a local one, or rules, one at a time."""
    row = inbox.get(target)
    choice = roles.choice("utility" if row and row["source"] == "spreadsheet" else "extraction")
    if choice == "rules" or ai.describe(choice)["local"]:
        return "default"
    return "cloud"


# ── Small helpers ─────────────────────────────────────────────────────

def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = dateparser.parse(value)
    except (ValueError, OverflowError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Date-only values land at noon UTC so they don't shift a day in most timezones.
        if dt.time() == dtime(0, 0):
            dt = dt.replace(hour=12)
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_partial_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    if re.fullmatch(r"\d{4}", value):
        return date(int(value), 1, 1)
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", value):
        return date(int(m.group(1)), int(m.group(2)), 1)
    try:
        return dateparser.parse(value, default=datetime(2000, 1, 1)).date()
    except (ValueError, OverflowError):
        return None


def _is_ai(extractor: str | None) -> bool:
    return bool(extractor) and extractor not in ("rules", "heuristic")


def _tags(tags: list[str]) -> list[str]:
    return store.normalize_tags(tags or [])


def owner_context() -> tuple[object | None, object | None, str | None, list]:
    """(owner, owner's organization, owner's title, teammates)."""
    owner = store.get_me()
    if owner is None:
        return None, None, None, []
    edge = db.one("SELECT target_id, properties FROM crm_relationships WHERE source_id = ? AND kind = 'works_at' "
                  "AND ended_at IS NULL LIMIT 1", (owner.id,))
    if edge is None:
        return owner, None, owner.attributes.get("title"), []
    org = store.get_entity(edge["target_id"])
    team = [store._entity(r) for r in db.query(
        "SELECT e.* FROM crm_entities e JOIN crm_relationships r ON r.source_id = e.id WHERE r.target_id = ? "
        "AND r.kind = 'works_at' AND r.ended_at IS NULL AND e.id != ? LIMIT 12", (edge["target_id"], owner.id))]
    import json
    title = (json.loads(edge["properties"] or "{}")).get("title") or owner.attributes.get("title")
    return owner, org, title, team


def relevant_known_entities(text_: str, cap: int = 150) -> list[tuple[str, str]]:
    """Existing names that plausibly appear in the text (full name or a name part)."""
    lowered = text_.lower()
    words = set(re.findall(r"[\w'-]{4,}", lowered))
    hits: list[tuple[str, str]] = []
    for e in snapshot.load().entities.values():
        if e.kind not in ("person", "organization", "topic"):
            continue
        n = e.name.lower()
        if n in lowered or any(part in words for part in re.findall(r"[\w'-]{4,}", n)):
            hits.append((e.name, e.kind))
            if len(hits) >= cap:
                break
    return hits


def known_tags(limit: int = 60) -> list[str]:
    count: dict[str, int] = {}
    for e in snapshot.load().entities.values():
        for t in e.tags or []:
            if t != "demo":
                count[t] = count.get(t, 0) + 1
    return [t for t, _ in sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


# ── Putting things in the inbox ───────────────────────────────────────

def queue(row_ids: list[str]) -> None:
    for row_id in row_ids:
        jobs.enqueue("crm", "extract", row_id)


def subject_person(subject_id: str | None):
    """The person a pasted report or file is about, when you said so (from a research flag)."""
    if not subject_id:
        return None
    person = store.get_entity(subject_id)
    if person is None or person.kind != "person" or person.is_self:
        raise ProposalError("That person is no longer in your book")
    return person


def create_note_job(text: str, title: str | None = None, occurred_at: str | None = None,
                    subject_id: str | None = None) -> dict:
    subject = subject_person(subject_id)
    row = inbox.create("manual_note", title=title or (f"Research on {subject.name}" if subject else None),
                       occurred_at=occurred_at, raw_text=text,
                       payload={"subject_id": subject.id} if subject else None)
    queue([row["id"]])
    return row


def create_file_jobs(files: list[tuple[str, bytes]], *, auto_apply: bool, subject_id: str | None = None) -> list[dict]:
    """One row per file. Duplicates (same text) and files that can't be read are recorded as skipped, and say why."""
    subject = subject_person(subject_id)
    existing = inbox.known_hashes()
    by_folder: dict[str, list[str]] = {}
    for path, _ in files:
        by_folder.setdefault(os.path.dirname(path), []).append(os.path.basename(path))

    rows: list[dict] = []
    seen: dict[str, str] = {}
    for path, data in files:
        filename, folder = os.path.basename(path), os.path.dirname(path)
        siblings = [n for n in by_folder.get(folder, []) if n != filename]
        payload = {"filename": filename, "folder": folder or None, "siblings": siblings, "auto_apply": auto_apply}
        if subject:
            payload["subject_id"] = subject.id
        fields: dict = {"source": "document", "title": PurePosixPath(filename).stem[:300], "status": "pending", "payload": payload}
        kind = kind_of(filename)
        try:
            if kind == "unsupported":
                ext = PurePosixPath(filename).suffix.lower()
                fields.update(status="skipped", error=(
                    "Audio and video need a transcript first; add the transcript file instead."
                    if ext in (".mp4", ".m4a", ".mp3", ".mov", ".wav") else f"Unsupported file type ({ext or 'none'})."))
            elif kind == "spreadsheet":
                sheets = parse_spreadsheet(filename, data)
                fields.update(source="spreadsheet", content_hash=text_hash(repr([s.rows for s in sheets])),
                              payload={**payload, "sheets": [{"name": s.name, "rows": s.rows} for s in sheets]})
                if not sheets:
                    fields.update(status="skipped", error="The spreadsheet has no rows.")
            else:
                doc = parse_document(filename, data)
                fields.update(raw_text=doc.text, content_hash=text_hash(doc.text), payload={
                    **payload, "words": doc.words, "created": doc.created.isoformat() if doc.created else None,
                    "warnings": doc.warnings})
                if doc.words < 15:
                    fields.update(status="skipped", error="File has no usable text.")
        except UnsupportedFile as e:
            fields.update(status="skipped", error=str(e))
        except Exception as e:  # noqa: BLE001 - a corrupt file shouldn't sink the batch
            log.exception("could not read %s", path)
            fields.update(status="failed", error=f"Could not read file: {e.__class__.__name__}")

        digest = fields.get("content_hash")
        if fields["status"] == "pending" and digest:
            if digest in existing:
                fields.update(status="skipped", error=("You discarded this file earlier." if existing[digest] == "discarded"
                                                       else "Already imported (same content)."))
            elif digest in seen:
                fields.update(status="skipped", error=f"Duplicate of {seen[digest]} in this upload.")
            else:
                seen[digest] = filename
        rows.append(inbox.create(**fields))
    queue([r["id"] for r in rows if r["status"] == "pending"])
    return rows


def _attendee_line(a: dict) -> str:
    name, email = a.get("name"), a.get("email")
    line = f"{name} <{email}>" if name and email else (name or email or "")
    return f"{line} (the CRM owner)" if a.get("is_self") else line


def create_meeting_job(*, origin: str = "granola", external_id: str | None = None, title: str | None = None,
                       started_at: str | None = None, attendees: list[dict] | None = None, notes: str | None = None,
                       transcript: str | None = None, auto_apply: bool = True) -> tuple[dict, bool]:
    """Queue a recorded meeting. Returns (row, already_imported).

    A meeting seen before (same origin and external id, or identical text) returns the earlier row instead of
    queuing a duplicate, so a sync can resend freely."""
    if external_id:
        earlier = db.one(
            "SELECT id FROM crm_inbox WHERE source = 'meeting' AND json_extract(payload, '$.origin') = ? "
            "AND json_extract(payload, '$.external_id') = ? AND status IN ('pending', 'processing', 'review', 'applied', 'discarded') "
            "ORDER BY created_at DESC LIMIT 1", (origin, external_id))
        if earlier:
            return inbox.require(earlier["id"]), True
    people = [a for a in (attendees or []) if a.get("name") or a.get("email")]
    sections = [f"Meeting: {title or 'Untitled meeting'}"]
    if started_at:
        sections.append(f"Date: {started_at}")
    if people:
        sections.append("Attendees: " + "; ".join(_attendee_line(a) for a in people))
    if notes and notes.strip():
        sections.append(f"## Notes from {origin}\n{notes.strip()}")
    if transcript and transcript.strip():
        sections.append(f"## Transcript\n{transcript.strip()}")
    raw = "\n\n".join(sections)[:MAX_MEETING_CHARS]
    if not (notes or transcript or "").strip():
        raise ProposalError("A meeting needs notes or a transcript")
    digest = text_hash(raw)
    earlier_row = inbox.with_hash(digest)
    if earlier_row:
        return earlier_row, True
    row = inbox.create("meeting", title=(title or "Untitled meeting")[:300], occurred_at=started_at, raw_text=raw,
                       content_hash=digest, payload={"origin": origin, "external_id": external_id, "attendees": people,
                                                     "auto_apply": auto_apply, "words": len(raw.split())})
    queue([row["id"]])
    return row, False


# ── Triage and extraction ─────────────────────────────────────────────

def heuristic_triage(filename: str, words: int) -> Triage:
    if re.search(r"www[._]|_content\b|scrape", filename, re.I):
        return Triage(category="reference_material", process="brief", reason="Looks like a saved web page.")
    if words < 15:
        return Triage(category="junk", process="skip", reason="No usable text.")
    return Triage(category="internal_document", process="full", reason="Default.")


def triage(row: dict) -> Triage:
    filename = row["payload"].get("filename") or row["title"] or ""
    words = row["payload"].get("words") or len((row["raw_text"] or "").split())
    if roles.choice("utility") == "rules" or words < 400:
        return heuristic_triage(filename, words)
    try:
        verdict, _ = roles.structured("utility", triage_prompt(filename, row["payload"].get("folder"), row["raw_text"] or "", words),
                                      TRIAGE_SYSTEM, Triage, 8000)
        return verdict  # type: ignore[return-value]
    except ai.AIError as e:
        log.warning("triage failed for %s: %s", filename, e)   # not worth stopping for: the default is to read it
        return heuristic_triage(filename, words)


def _subject_line(row: dict) -> str | None:
    person = store.get_entity(row["payload"]["subject_id"]) if row["payload"].get("subject_id") else None
    if person is None or person.kind != "person":
        return None
    employer = views.get().employer(person.id)
    sub = subtitle_for(person, employer.name if employer else None)
    return f"{person.name} ({sub})" if sub else person.name


def _force_subject(row: dict, extraction: Extraction) -> str | None:
    """You said who this text is about: make that person the subject of a person profile, whatever the reader made of
    it. Returns their id."""
    person = store.get_entity(row["payload"]["subject_id"]) if row["payload"].get("subject_id") else None
    if person is None or person.kind != "person":
        return None
    extraction.doc_type = "person_profile"
    people = [e for e in extraction.entities if e.kind == "person"]
    best = max(people, key=lambda e: resolve.similarity(e.name, person.name), default=None)
    if best is None or resolve.similarity(best.name, person.name) < MATCH_THRESHOLD:
        refs = {e.ref for e in extraction.entities}
        ref = next(r for r in (f"s{n}" for n in range(1, 1000)) if r not in refs)
        best = ExtractedEntity(ref=ref, kind="person", name=person.name, role="subject")
        extraction.entities.append(best)
    best.name, best.role = person.name, "subject"
    extraction.subject_ref = best.ref
    return person.id


def build_context(row: dict, local: bool, brief: bool, warnings: list[str]) -> DocContext:
    owner, org, title, team = owner_context()
    body = row["raw_text"] or ""
    if brief and len(body) > BRIEF_MAX_CHARS:
        body = body[:BRIEF_MAX_CHARS]
        warnings.append("Long reference material: only the opening was read.")
    if local:
        limit = (32768 - 6000) * 3
        if len(body) > limit:
            body = body[:limit]
            warnings.append("Text was cut to fit the local model's context window; key details near the end may be missing.")
    occurred = parse_dt(row["occurred_at"])
    return DocContext(
        text=body,
        title=row["title"] if row["source"] != "document" else None,
        occurred_on=occurred.date().isoformat() if occurred else None,
        filename=row["payload"].get("filename"),
        folder=row["payload"].get("folder"),
        siblings=row["payload"].get("siblings") or [],
        owner_name=owner.name if owner else None,
        owner_org=org.name if org else None,
        owner_title=title,
        teammates=[t.name for t in team],
        known_entities=[n for n, _ in relevant_known_entities(body)],
        known_tags=known_tags(),
        subject=_subject_line(row),
        attendees=[_attendee_line(a) for a in row["payload"].get("attendees") or []],
        brief=brief,
    )


def run_extraction(row: dict, *, brief: bool, warnings: list[str]) -> tuple[Extraction, str]:
    """(what was found, who found it: "anthropic:claude-opus-5-5", or "rules")."""
    choice = roles.choice("extraction")
    if choice != "rules":
        ctx = build_context(row, ai.describe(choice)["local"], brief, warnings)
        try:
            extraction, pid = roles.structured("extraction", extraction_prompt(ctx), EXTRACTION_SYSTEM, Extraction)
            return extraction, f"{pid}:{ai.describe(pid)['model']}"  # type: ignore[return-value]
        except ai.AIError as e:
            if e.provider_down:
                # Don't quietly degrade every document: stop, and let the batch wait.
                raise ProviderDown(f"AI provider unavailable: {e}") from e
            log.warning("AI extraction failed for %s: %s", row["id"], e)
            warnings.append(f"{FALLBACK_WARNING_PREFIX} ({e}); used rule-based extraction instead.")
    owner = store.get_me()
    occurred = parse_dt(row["occurred_at"])
    extraction = extract_heuristic(
        row["raw_text"] or "",
        title=row["title"] if row["source"] != "document" else None,
        occurred_on=occurred.date().isoformat() if occurred else None,
        owner_name=owner.name if owner else None,
        known_entities=relevant_known_entities(row["raw_text"] or ""),
    )
    return extraction, "rules"


# ── Proposals ─────────────────────────────────────────────────────────

def _candidates(candidates: list[resolve.Candidate]) -> list[dict]:
    v = views.get()

    def subtitle(e) -> str | None:
        employer = v.employer(e.id) if e.kind == "person" else None
        return subtitle_for(e, employer.name if employer else None)

    return [c.as_dict(subtitle(c.entity)) for c in candidates]


def build_proposal(row: dict, extraction: Extraction, warnings: list[str], *, brief: bool = False) -> dict:
    owner = store.get_me()
    if row["source"] == "meeting":
        extraction.doc_type = "meeting_notes"  # a recording is a meeting, whatever the model thought
    forced_id = _force_subject(row, extraction)
    occurred = parse_dt(row["occurred_at"]) or parse_dt(extraction.occurred_on) or parse_iso(row["created_at"])
    refs = {e.ref for e in extraction.entities}
    subject = extraction.subject_ref if extraction.doc_type in PROFILE_TYPES and extraction.subject_ref in refs else None
    record_kind = "meeting" if extraction.doc_type == "meeting_notes" else "document"
    include_record = subject is None or brief

    entities: list[dict] = []
    kinds_by_ref: dict[str, str] = {RECORD_REF: record_kind}
    for ent in extraction.entities:
        if ent.ref in kinds_by_ref:
            continue
        kinds_by_ref[ent.ref] = ent.kind
        is_owner = bool(owner and ent.kind == "person" and ent.name.strip().lower() == owner.name.lower())
        candidates = resolve.find_candidates(ent.kind, ent.name, ent.email)
        match, ambiguous = resolve.pick_match(candidates, MATCH_THRESHOLD)
        if is_owner:
            match_id, ambiguous = owner.id, False
        elif forced_id and ent.ref == subject:
            match_id, ambiguous = forced_id, False
        else:
            match_id = match.entity.id if match else None
        entities.append({
            "ref": ent.ref, "kind": ent.kind, "name": ent.name,
            "role": "subject" if ent.ref == subject else ent.role,
            "title": ent.title, "email": ent.email, "location": ent.location, "linkedin_url": ent.linkedin_url,
            "website": ent.website, "summary": ent.summary, "tags": _tags(ent.tags), "facts": ent.facts,
            "action": "link" if match_id else "create", "match_id": match_id, "ambiguous": ambiguous,
            "is_self": is_owner, "candidates": _candidates(candidates),
        })

    if record_kind == "meeting":
        _merge_invitees(row, entities, kinds_by_ref, owner)

    relationships: list[dict] = []

    def add(source: str, target: str, kind: str, context: str | None = None, started=None, ended=None) -> None:
        relationships.append({"id": f"r{len(relationships) + 1}", "source": source, "target": target, "kind": kind,
                              "context": context, "started": started, "ended": ended, "include": True})

    if include_record:
        for ent in entities:
            role = ent["role"]
            if record_kind == "meeting":
                kind = "attended" if ent["kind"] == "person" and role in ("attendee", "author") else "discussed_in"
            elif role == "author" and ent["kind"] in ("person", "organization"):
                kind = "authored"
            elif role == "subject":
                kind = "about"
            else:
                kind = "mentioned_in"
            if ent["kind"] == "document" and kind != "about":
                kind = "related_to"
            add(ent["ref"], RECORD_REF, kind)
    # Smaller models sometimes reference entities by name ("Alex_Rivera") instead of ref.
    by_name = {re.sub(r"[\s_]+", " ", e["name"]).strip().lower(): e["ref"] for e in entities}

    def ref_of(value: str) -> str | None:
        if value in kinds_by_ref:
            return value
        return by_name.get(re.sub(r"[\s_]+", " ", value).strip().lower())

    for rel in extraction.relationships:
        source, target = ref_of(rel.source), ref_of(rel.target)
        if source is None or target is None or source == target:
            continue
        if err := validate_relationship(rel.kind, kinds_by_ref[source], kinds_by_ref[target]):
            warnings.append(f"Dropped relationship: {err}")
            continue
        add(source, target, rel.kind, rel.context, rel.started, rel.ended)

    existing = None
    if include_record and record_kind == "meeting":
        people = {e["match_id"] for e in entities if e["match_id"] and e["role"] == "attendee" and not e["is_self"]}
        existing = find_existing_meeting(occurred, people, extraction.title or row["title"] or "",
                                         row["payload"].get("origin"), row["payload"].get("external_id"))
        if existing:
            warnings.append(f"Adds to the existing meeting “{existing.name}” instead of creating a new one.")

    return {
        "version": 2,
        "doc_type": extraction.doc_type,
        "record": {
            "include": include_record, "kind": record_kind, "match_id": existing.id if existing else None,
            "title": extraction.title, "occurred_at": iso(occurred),
            "summary": extraction.summary, "key_points": extraction.key_points, "action_items": extraction.action_items,
            "tags": _tags(extraction.tags),
        },
        "subject_ref": subject,
        "entities": entities,
        "relationships": relationships,
        "warnings": warnings,
    }


def _merge_invitees(row: dict, entities: list[dict], kinds_by_ref: dict[str, str], owner) -> None:
    """Make every calendar invitee an attendee, with their email, even if the AI missed them."""
    invitees = row["payload"].get("attendees") or []
    if not invitees:
        return
    people = [e for e in entities if e["kind"] == "person"]
    by_email = {e["email"].lower(): e for e in people if e.get("email")}
    by_name = {e["name"].strip().lower(): e for e in people}
    for i, a in enumerate(invitees):
        name = (a.get("name") or "").strip()
        email = (a.get("email") or "").strip() or None
        ent = (by_email.get(email.lower()) if email else None) or by_name.get(name.lower())
        if ent is None and a.get("is_self") and owner:
            ent = next((e for e in people if e.get("match_id") == owner.id), None)
        if ent is None:
            display = name or (email.split("@")[0].replace(".", " ").title() if email else "")
            if not display:
                continue
            ent = {"ref": f"invitee{i + 1}", "kind": "person", "name": display, "role": "attendee", "title": None,
                   "email": email, "location": None, "linkedin_url": None, "website": None, "summary": None, "tags": [],
                   "facts": [], "action": "create", "match_id": None, "ambiguous": False, "is_self": False, "candidates": []}
            entities.append(ent)
            kinds_by_ref[ent["ref"]] = "person"
            people.append(ent)
        if ent["role"] != "subject":
            ent["role"] = "attendee"
        if email and not ent.get("email"):
            ent["email"] = email
        if a.get("is_self") and owner:
            ent.update(match_id=owner.id, action="link", ambiguous=False, is_self=True, candidates=[])
            continue
        if not ent["is_self"] and (ent["action"] == "create" or ent["ambiguous"]):
            # An email is the most reliable key there is: re-match with it.
            candidates = resolve.find_candidates("person", ent["name"], ent.get("email"))
            match, ambiguous = resolve.pick_match(candidates, MATCH_THRESHOLD)
            if match:
                ent.update(match_id=match.entity.id, action="link", ambiguous=ambiguous)
            ent["candidates"] = _candidates(candidates)


def find_existing_meeting(occurred: datetime | None, people: set[str], title: str, origin: str | None,
                          external_id: str | None):
    """The same meeting imported earlier: by recorder id, else same day with shared attendees or a similar title."""
    if origin and external_id and re.fullmatch(r"[\w.-]{1,32}", origin):
        found = db.one("SELECT id FROM crm_entities WHERE kind = 'meeting' AND json_extract(attributes, ?) = ?",
                       (f'$.external_ids."{origin}"', external_id))
        if found:
            return store.get_entity(found["id"])
    if occurred is None:
        return None
    lo, hi = iso(occurred - timedelta(hours=36)), iso(occurred + timedelta(hours=36))
    best, best_score = None, 0.0
    for m in db.query("SELECT * FROM crm_entities WHERE kind = 'meeting' AND occurred_at BETWEEN ? AND ?", (lo, hi)):
        attended = {r["source_id"] for r in db.query(
            "SELECT source_id FROM crm_relationships WHERE target_id = ? AND kind = 'attended'", (m["id"],))}
        overlap = len(people & attended)
        similar = SequenceMatcher(None, title.lower(), m["name"].lower()).ratio()
        if not (overlap or similar >= 0.6):
            continue
        score = overlap + similar
        if score > best_score:
            best, best_score = m, score
    return store.get_entity(best["id"]) if best else None


def needs_review(proposal: dict) -> bool:
    """Auto-apply is safe unless a name matched several records or the AI step fell back to rules."""
    if any(w.startswith(FALLBACK_WARNING_PREFIX) for w in proposal.get("warnings", [])):
        return True
    return any(e.get("ambiguous") and e.get("action") != "skip" for e in proposal.get("entities", []))


# ── Applying ──────────────────────────────────────────────────────────

def _validate(proposal: dict) -> None:
    if not isinstance(proposal.get("entities"), list) or not isinstance(proposal.get("relationships"), list):
        raise ProposalError("Proposal must contain 'entities' and 'relationships' lists")
    if not isinstance(proposal.get("record"), dict):
        raise ProposalError("Proposal must contain a 'record' object")
    if proposal["record"].get("kind") not in ("meeting", "document"):
        raise ProposalError("record.kind must be meeting or document")
    for ent in proposal["entities"]:
        if ent.get("action") not in ("create", "link", "skip"):
            raise ProposalError(f"Entity {ent.get('ref')}: action must be create, link or skip")
        if ent.get("action") == "link" and not ent.get("match_id"):
            raise ProposalError(f"Entity {ent.get('name')}: choose a record to link to")
        if ent.get("action") == "create" and not (ent.get("name") or "").strip():
            raise ProposalError(f"Entity {ent.get('ref')}: name is required")


def _existing_exact(c, kind: str, name: str, email: str | None):
    """Exact email or name/alias match: catches records created since the proposal was built."""
    if email:
        row = c.execute("SELECT * FROM crm_entities WHERE kind = ? AND lower(json_extract(attributes, '$.email')) = ? LIMIT 1",
                        (kind, email.lower())).fetchone()
        if row:
            return store._entity(row)
    rows = c.execute("SELECT * FROM crm_entities WHERE kind = ? AND lower(name) = ?", (kind, name.lower())).fetchall()
    if len(rows) == 1:
        return store._entity(rows[0])
    row = c.execute("SELECT e.* FROM crm_entities e, json_each(COALESCE(json_extract(e.attributes, '$.aliases'), '[]')) a "
                    "WHERE e.kind = ? AND lower(a.value) = ? LIMIT 1", (kind, name.lower())).fetchone()
    return store._entity(row) if row else None


def apply_proposal(row_id: str, proposal: dict) -> dict:
    """Writes a proposal into the graph in one transaction (all of it, or none). Serialized."""
    with _apply_lock:
        result, new_actions, record_id = _apply(row_id, proposal)
    store._touch()  # the writes above touched too early, before they were committed
    if new_actions and record_id:
        events.publish(contracts.ACTIONS_FOUND, {"source_ref": f"crm:{record_id}", "items": new_actions})
    return result


def _apply(row_id: str, proposal: dict) -> tuple[dict, list[str], str | None]:
    row = inbox.require(row_id)
    if row["status"] not in ("review", "failed"):
        raise ProposalError(f"This item is {row['status']}; only items awaiting review can be applied")
    _validate(proposal)

    # Everything an automatic sync brings in is stamped with where it came from ("granola"), so it can be found
    # and removed together (capture.remove_source).
    source_label = row["payload"].get("origin") or ("ai" if _is_ai(row["extractor"]) else "ingest")
    payload = row["payload"]
    ids: dict[str, str] = {}
    kinds: dict[str, str] = {}
    counts = {"created": 0, "linked": 0, "relationships": 0, "notes": 0}
    spec = proposal["record"]
    occurred = parse_dt(spec.get("occurred_at")) or parse_dt(row["occurred_at"]) or parse_iso(row["created_at"])
    external = ({payload["origin"]: payload["external_id"]} if payload.get("origin") and payload.get("external_id") else {})
    new_actions: list[str] = []

    with db.connect() as c:
        record = None
        existing = store.get_entity(str(spec["match_id"]), c) if spec.get("match_id") else None
        if spec.get("include", True) and existing is not None:
            # Same meeting as one already on file: enrich it rather than duplicate it.
            attrs = dict(existing.attributes or {})
            before = list(attrs.get("action_items") or [])
            for key in ("key_points", "action_items"):
                attrs[key] = list(dict.fromkeys([*(attrs.get(key) or []), *(spec.get(key) or [])]))
            # The tasks module replaces a source's open tasks with the list it's given, so send the whole list, and
            # only when something was added.
            new_actions = attrs["action_items"] if attrs["action_items"] != before else []
            if external:
                attrs["external_ids"] = {**(attrs.get("external_ids") or {}), **external}
            fields: dict = {"attributes": attrs, "tags": _tags([*(existing.tags or []), *(spec.get("tags") or [])])[:20]}
            if not existing.summary and spec.get("summary"):
                fields["summary"] = spec["summary"]
            if existing.occurred_at is None:
                fields["occurred_at"] = occurred
            record = store.update_entity(existing.id, conn=c, **fields)
            ids[RECORD_REF], kinds[RECORD_REF] = record.id, record.kind
            counts["linked"] += 1
        elif spec.get("include", True):
            attrs = {"action_items": spec.get("action_items") or [], "key_points": spec.get("key_points") or [],
                     "ingestion_job_id": row_id}
            if payload.get("filename"):
                attrs["source_file"] = payload["filename"]
            if external:
                attrs["external_ids"] = external
            if spec["kind"] == "document" and proposal.get("doc_type"):
                attrs["doc_type"] = proposal["doc_type"].replace("_", " ")
            record = store.create_entity(spec["kind"], (spec.get("title") or row["title"] or "Untitled").strip(),
                                         summary=spec.get("summary"), attributes=attrs, tags=_tags(spec.get("tags") or []),
                                         occurred_at=occurred, source=source_label, conn=c)
            ids[RECORD_REF], kinds[RECORD_REF] = record.id, record.kind
            counts["created"] += 1
            new_actions = list(attrs["action_items"])

        titles: dict[str, str] = {}
        for ent in proposal["entities"]:
            if ent["action"] == "skip":
                continue
            if ent["action"] == "link":
                entity = store.get_entity(str(ent["match_id"]), c)
                if entity is None:
                    raise ProposalError(f"The record for {ent.get('name')} no longer exists")
                counts["linked"] += 1
            else:
                entity = _existing_exact(c, ent["kind"], ent["name"].strip(), ent.get("email"))
                if entity:
                    counts["linked"] += 1
                else:
                    entity = store.create_entity(ent["kind"], ent["name"].strip(), source=source_label, conn=c)
                    counts["created"] += 1
            attrs = dict(entity.attributes or {})
            for key in ("title", "email", "location", "linkedin_url", "website"):
                if ent.get(key) and not attrs.get(key):
                    attrs[key] = str(ent[key])[:300]
            fields = {"attributes": attrs}
            if ent.get("summary") and not entity.summary:
                fields["summary"] = ent["summary"]
            if ent.get("tags"):
                fields["tags"] = _tags([*(entity.tags or []), *ent["tags"]])[:20]
            entity = store.update_entity(entity.id, conn=c, **fields)
            ids[ent["ref"]], kinds[ent["ref"]] = entity.id, entity.kind
            if ent.get("title"):
                titles[ent["ref"]] = ent["title"]
            for fact in ent.get("facts") or []:
                if fact and fact.strip():
                    store.add_note(entity.id, fact.strip(), occurred_at=occurred, source=source_label,
                                   evidence_id=record.id if record else None, conn=c)
                    counts["notes"] += 1

        if proposal.get("doc_type") == "person_profile" and ids.get(proposal.get("subject_ref") or ""):
            research.mark_done(ids[proposal["subject_ref"]], c)

        # Keep the original text: on the record, or on the profile's subject.
        if row["raw_text"]:
            target = record.id if record else ids.get(proposal.get("subject_ref") or "")
            if target:
                heading = spec.get("title") or row["title"] or "Source"
                body = row["raw_text"] if record else f"{heading}\n\n{row['raw_text']}"
                store.add_note(target, body, occurred_at=occurred,
                               source="document" if row["source"] == "document" else payload.get("origin") or "ingest",
                               evidence_id=record.id if record else None, conn=c)
                counts["notes"] += 1

        for rel in proposal["relationships"]:
            if not rel.get("include", True):
                continue
            s, t = ids.get(rel["source"]), ids.get(rel["target"])
            if s is None or t is None or s == t:
                continue
            if validate_relationship(rel["kind"], kinds[rel["source"]], kinds[rel["target"]]):
                continue
            props = {"context": rel["context"]} if rel.get("context") else {}
            if rel["kind"] == "works_at" and titles.get(rel["source"]) and not rel.get("ended"):
                props["title"] = titles[rel["source"]]
            _, created = store.upsert_edge(s, t, rel["kind"], properties=props, conn=c, source=source_label,
                                           evidence_id=record.id if record else None,
                                           started_at=parse_partial_date(rel.get("started")),
                                           ended_at=parse_partial_date(rel.get("ended")))
            counts["relationships"] += int(created)

        result = {**counts, "record_id": record.id if record else None, "record_kind": record.kind if record else None,
                  "subject_id": ids.get(proposal.get("subject_ref") or ""), "entity_ids": dict(ids)}
        inbox.update(row_id, conn=c, proposal=proposal, status="applied", error=None, result=result)
    return result, new_actions if (record and record.kind == "meeting") else [], record.id if record else None


def apply_ready() -> dict:
    """Apply every item waiting for review, except those with ambiguous matches or a rules-only reading."""
    applied = held = 0
    for item in inbox.listing(["review"], 500):
        row = inbox.require(item["id"])
        if not row["proposal"] or row["proposal"].get("kind") == "spreadsheet" or needs_review(row["proposal"]):
            held += 1
            continue
        try:
            apply_proposal(row["id"], row["proposal"])
            applied += 1
        except ProposalError:
            held += 1
    return {"applied": applied, "held": held}


def discard(row_id: str) -> dict:
    row = inbox.require(row_id)
    if row["status"] == "applied":
        raise ProposalError("Applied items can't be discarded")
    inbox.update(row_id, status="discarded")
    jobs.cancel_for("crm", row_id)
    return inbox.require(row_id)


def retry(row_id: str) -> dict:
    row = inbox.require(row_id)
    if row["status"] == "applied" or not (row["raw_text"] or row["source"] == "spreadsheet"):
        raise ProposalError("Only unapplied items with text can be read again")
    inbox.update(row_id, status="pending", proposal=None, error=None)
    queue([row_id])
    return inbox.require(row_id)


# ── Spreadsheets ──────────────────────────────────────────────────────

def process_spreadsheet(row: dict, job: jobs.Job | None = None) -> None:
    """Map each sheet's columns (AI, with a synonym fallback), then import the rows. All of it or none of it, and
    it's recorded as applied: there's no per-row review, but the mapping used is kept to look at afterwards.
    payload["mappings"] (sheet name -> mapping) replays a recorded mapping instead of asking."""
    owner, _, _, team = owner_context()
    sheets = [ParsedSheet(s["name"], s["rows"]) for s in row["payload"].get("sheets", [])]
    filename = row["payload"].get("filename") or row["title"] or "spreadsheet"
    given = row["payload"].get("mappings") or {}
    mappings: dict[str, spreadsheets.SheetMapping] = {}
    recorded: dict[str, dict] = {}
    how: set[str] = set()
    if job:
        job.stage("Reading the columns")
    try:
        for sheet in sheets:
            if sheet.name in given:
                mapping, by = spreadsheets.SheetMapping.model_validate(given[sheet.name]), given[sheet.name].get("mapped_by", "recorded")
            else:
                mapping, by = spreadsheets.map_sheet(filename, sheet, owner.name if owner else None, [t.name for t in team])
            mappings[sheet.name] = mapping
            recorded[sheet.name] = {**mapping.model_dump(), "mapped_by": by}
            how.add(by)
    except ai.AIError as e:
        if e.provider_down:
            raise ProviderDown(f"AI provider unavailable: {e}") from e
        raise
    if job:
        job.stage("Adding the people")
    with _apply_lock:
        with db.connect() as c:
            importer = spreadsheets.SheetImporter(c, owner, [*team, *([owner] if owner else [])], "spreadsheet")
            for sheet in sheets:
                importer.import_sheet(sheet, mappings[sheet.name], None)
            inbox.update(row["id"], conn=c, status="applied", error=None, result=importer.stats, extractor=", ".join(sorted(how)) or "rules",
                         proposal={"version": 2, "kind": "spreadsheet", "sheets": recorded})
    store._touch()


# ── The host job: read one inbox item ─────────────────────────────────

def handle_extract(job: jobs.Job) -> None:
    """Triage, extract, build the proposal, and apply it when it's safe. Safe to run twice: it only touches an item
    that's still waiting (or was cut off mid-read)."""
    row = inbox.get(job.target)
    if row is None or row["status"] not in ("pending", "processing", "failed"):
        return
    if not job.forced and (reason := _breaker()):
        raise jobs.Wait(f"{reason}. Press Resume when it's fixed.")
    inbox.update(row["id"], status="processing", error=None)
    try:
        if row["source"] == "spreadsheet":
            process_spreadsheet(row, job)
            return
        warnings = list(row["payload"].get("warnings") or [])
        brief = False
        payload = dict(row["payload"])
        if row["source"] == "document" and not payload.get("subject_id"):   # research you filed on someone is always read
            job.stage("Sorting")
            verdict = triage(row)
            payload["triage"] = verdict.model_dump()
            if verdict.process == "skip":
                inbox.update(row["id"], status="skipped", error=verdict.reason, payload=payload)
                return
            brief = verdict.process == "brief"
        job.stage("Reading")
        extraction, extractor = run_extraction(row, brief=brief, warnings=warnings)
        job.stage("Matching names")
        proposal = build_proposal(row, extraction, warnings, brief=brief)
        inbox.update(row["id"], status="review", proposal=proposal, extractor=extractor, payload=payload)
    except ProviderDown as e:
        inbox.update(row["id"], status="pending", error=None)   # back in line
        _trip(str(e))
        raise jobs.Wait(f"{e}. Press Resume when it's fixed.") from e
    except Exception as e:  # noqa: BLE001 - shown on the item, with Retry
        log.exception("reading %s failed", row["id"])
        inbox.update(row["id"], status="failed", error=str(e) or e.__class__.__name__)
        raise

    if payload.get("auto_apply") and not needs_review(proposal):
        job.stage("Adding to your people")
        try:
            apply_proposal(row["id"], proposal)
        except ProposalError as e:
            log.warning("auto-apply of %s held: %s", row["id"], e)
            inbox.update(row["id"], error=str(e))
