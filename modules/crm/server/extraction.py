"""What the AI is asked to produce from a note or document, and the prompts and rule-based stand-in around it.

Extraction models double as the JSON schema the AI must fill, so the field descriptions are part of the prompt:
keep them precise. The system prompts stay the same on every call (cache-friendly); per-document context goes in
the user message. The rule-based extractor is used only when you pick "rules" for the job, or when the AI
answered but not in a usable shape; either way a person reviews the result before anything is applied.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


DocType = Literal["meeting_notes", "person_profile", "organization_profile", "document"]
ExtractedKind = Literal["person", "organization", "topic", "document"]
Role = Literal["attendee", "mentioned", "author", "subject"]
ExtractedRelKind = Literal[
    "works_at",
    "advises",
    "invested_in",
    "introduced_by",
    "knows",
    "reports_to",
    "partner_of",
    "part_of",
    "related_to",
]


class ExtractedEntity(BaseModel):
    ref: str = Field(description="Short unique id within this output, e.g. 'p1', 'o2', 't1'.")
    kind: ExtractedKind
    name: str = Field(
        description="Full name. Use the exact spelling of a known entity when it is the same one. For people known only by first name, use the full name if the text or known entities make it unambiguous."
    )
    role: Role = Field(
        description="attendee: took part in the meeting. subject: the person/organization a profile document is about. author: wrote the document. mentioned: everything else."
    )
    title: str | None = Field(default=None, description="Current job title (people only).")
    email: str | None = Field(default=None, description="Email address exactly as written in the text.")
    location: str | None = Field(default=None, description="City/region if stated.")
    linkedin_url: str | None = Field(default=None, description="LinkedIn URL if it appears in the text.")
    website: str | None = Field(default=None, description="Website (organizations) if it appears in the text.")
    summary: str | None = Field(
        default=None,
        description="1-3 sentence neutral description for their profile: who they are and why they matter to the CRM owner. Required for the subject of a profile; otherwise only when the text says something substantive.",
    )
    tags: list[str] = Field(default_factory=list, description="0-5 tags (see tagging rules).")
    facts: list[str] = Field(
        default_factory=list,
        description="Durable, specific facts worth remembering (background, preferences, commitments, interests, how they can help). One sentence each, at most 6. No meeting logistics.",
    )


class ExtractedRelationship(BaseModel):
    source: str = Field(description="ref of the source entity")
    target: str = Field(description="ref of the target entity")
    kind: ExtractedRelKind = Field(
        description="works_at: person->organization (current or past employer). advises: person->person|organization. invested_in: person|organization->organization. introduced_by: person->the person who introduced them. knows: person<->person. reports_to: person->manager. partner_of: organization<->organization. part_of: organization|topic->organization|topic. related_to: anything else."
    )
    context: str | None = Field(default=None, description="One short phrase of evidence.")
    started: str | None = Field(default=None, description="Start as YYYY, YYYY-MM or YYYY-MM-DD if stated.")
    ended: str | None = Field(default=None, description="End as YYYY, YYYY-MM or YYYY-MM-DD if the relationship is over.")


class Extraction(BaseModel):
    doc_type: DocType = Field(
        description="meeting_notes: notes or a transcript of a call/meeting/event. person_profile: research or a bio about one person. organization_profile: research about one organization. document: anything else (plans, briefs, applications, agreements, presentations, research)."
    )
    title: str = Field(description="Concise title, max ~10 words. For meetings: who/what, e.g. 'Advisory call with Nora Linden'.")
    occurred_on: str | None = Field(
        default=None, description="Meeting date (or document date) as YYYY-MM-DD, inferred from the text, file name or folder when possible."
    )
    summary: str = Field(description="3-6 sentence summary written as high-quality notes: purpose, what was discussed, outcomes.")
    key_points: list[str] = Field(
        default_factory=list,
        description="The important points, decisions, numbers, and insights, as concise bullets (up to 12). Specific over generic.",
    )
    action_items: list[str] = Field(default_factory=list, description="Follow-ups, each starting with the owner's name when known.")
    tags: list[str] = Field(default_factory=list, description="0-6 tags for this meeting/document (see tagging rules).")
    subject_ref: str | None = Field(default=None, description="For person_profile / organization_profile: ref of the entity the document is about.")
    entities: list[ExtractedEntity]
    relationships: list[ExtractedRelationship] = Field(default_factory=list)


class Triage(BaseModel):
    """Cheap first look at a file, done by the utility model."""

    category: Literal[
        "meeting_notes", "person_profile", "organization_profile", "internal_document", "reference_material", "junk"
    ]
    process: Literal["full", "brief", "skip"] = Field(
        description="full: extract everything. brief: long generic reference material (web page dumps, market data) - record it with a summary only. skip: empty, boilerplate, or unusable."
    )
    reason: str = Field(description="One short sentence.")


# ── Prompts ───────────────────────────────────────────────────────────

EXTRACTION_SYSTEM = """You are the note-taker and archivist for a personal CRM that works as a knowledge graph. You read one meeting transcript, set of notes, or document at a time and turn it into structured records.

Goals, in order:
1. Write high-quality notes: an accurate summary, the key points and decisions, and clear action items. Be specific (names, numbers, dates, commitments); never pad.
2. Identify the people, organizations and substantive topics involved, with each person's role in this text.
3. Record only relationships the text supports: employers, who introduced whom, who advises or invested in what, partnerships.
4. Keep durable facts about people and organizations that the CRM owner would want to remember before the next conversation.

Rules:
- Never invent names, emails, titles, dates, or relationships. Prefer fewer, correct entities over many speculative ones.
- Transcripts are noisy: fix obvious speech-to-text misspellings of names when the correct spelling is clear from context or the known-entities list.
- The CRM owner and their team appear in many documents: include them only when they took part or are materially discussed.
- Topics are reusable themes (e.g. "cold chain logistics", "angel investing", "vaccine distribution"), not one-off phrases. At most 5 topics.
- Skip generic references (e.g. "Google", "LinkedIn", "the government") unless they matter to the relationship.
- For a profile document, set subject_ref to the entity it is about and put their background in summary and facts; include their current and notable past employers as works_at relationships (with started/ended when stated).

Tagging rules: tags are lowercase-hyphenated, 1-3 words. Reuse existing tags whenever one fits. Good dimensions: role (investor, angel-investor, vc, advisor, mentor, founder, ngo, foundation, government, university, accelerator, customer, partner, supplier, service-provider, media), sector (cold-chain, vaccines, global-health, medtech, climate, agtech), geography (oregon, portland, washington), and stage for people/orgs the owner is pursuing (prospect, warm-lead, active, champion)."""

TRIAGE_SYSTEM = """You sort files for import into a personal CRM. Given a file's name, location and opening text, classify it and decide how much processing it deserves. Web page dumps, scraped sites and long generic market data are reference_material with process "brief". Empty or unreadable files are junk with process "skip". Everything that mentions specific people, meetings, or the owner's own company is worth "full"."""


@dataclass
class DocContext:
    text: str
    title: str | None = None
    occurred_on: str | None = None
    filename: str | None = None
    folder: str | None = None
    siblings: list[str] = field(default_factory=list)
    owner_name: str | None = None
    owner_org: str | None = None
    owner_title: str | None = None
    teammates: list[str] = field(default_factory=list)
    known_entities: list[str] = field(default_factory=list)
    known_tags: list[str] = field(default_factory=list)
    attendees: list[str] = field(default_factory=list)
    brief: bool = False


def extraction_prompt(ctx: DocContext, today: date | None = None) -> str:
    today = today or date.today()
    parts = [f"Today's date: {today.isoformat()}."]
    if ctx.owner_name:
        who = ctx.owner_name
        if ctx.owner_title or ctx.owner_org:
            who += f" ({', '.join(p for p in (ctx.owner_title, ctx.owner_org) if p)})"
        parts.append(f"The CRM owner is {who}.")
        if ctx.teammates:
            parts.append("Owner's team: " + ", ".join(ctx.teammates) + ".")
        parts.append("If this is a meeting and the owner took part (usually true for notes they kept), include them as an attendee.")
    if ctx.filename:
        parts.append(f"File name: {ctx.filename}")
    if ctx.folder:
        parts.append(f"Folder: {ctx.folder}")
    if ctx.siblings:
        parts.append("Other files in the same folder: " + "; ".join(ctx.siblings[:15]))
    if ctx.filename or ctx.folder:
        parts.append(
            "Dates in file or folder names like 9_11, 09-12 or 0603 are month/day; resolve the year from the text, "
            "sibling files, or else as the most recent such date on or before today."
        )
    if ctx.title:
        parts.append(f"Title given by the user: {ctx.title}")
    if ctx.occurred_on:
        parts.append(f"Date given by the user: {ctx.occurred_on}")
    if ctx.attendees:
        parts.append(
            "This is a recorded meeting. Attendees from the calendar invite (all of them attended; use these exact "
            "names and include their emails):\n" + "\n".join(f"- {a}" for a in ctx.attendees)
        )
    if ctx.known_entities:
        parts.append("Known entities already in the CRM (reuse exact spelling):\n" + "\n".join(f"- {n}" for n in ctx.known_entities))
    if ctx.known_tags:
        parts.append("Existing tags (reuse when they fit): " + ", ".join(ctx.known_tags))
    if ctx.brief:
        parts.append(
            "This file is long reference material. Record it as a document with a summary and key points; "
            "only extract entities that are clearly important to the owner."
        )
    parts.append(f"<content>\n{ctx.text}\n</content>")
    return "\n\n".join(parts)


def triage_prompt(filename: str, folder: str | None, text: str, words: int) -> str:
    head = text[:4000]
    return (
        f"File name: {filename}\nFolder: {folder or '-'}\nLength: {words} words\n\n"
        f"<opening_text>\n{head}\n</opening_text>"
    )


# ── Rules instead of AI ───────────────────────────────────────────────

ATTENDEES_RE = re.compile(r"^\s*(?:attendees|participants|present|people)\s*[:\-]\s*(.+)$", re.I | re.M)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
NAME_ORG_RE = re.compile(r"^(?P<name>[^()<>]+?)\s*\((?P<org>[^)]+)\)$")
NAME_EMAIL_RE = re.compile(r"^(?P<name>[^<>]+?)\s*<(?P<email>[^>]+)>$")
ACTION_RE = re.compile(r"^\s*(?:[-*]\s*\[ ?\]\s*|todo[:\s]+|action(?: item)?s?[:\s]+|ai[:\s]+|next step[s]?[:\s]+)(.+)$", re.I)
DATE_RE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")


def _split_people(line: str) -> list[str]:
    parts = re.split(r",|;|\band\b|&", line)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def extract_heuristic(
    text: str,
    *,
    title: str | None = None,
    occurred_on: str | None = None,
    owner_name: str | None = None,
    known_entities: list[tuple[str, str]] | None = None,
) -> Extraction:
    entities: dict[str, ExtractedEntity] = {}
    relationships: list[ExtractedRelationship] = []

    def ref_for(kind: str, name: str, role: str, email: str | None = None) -> str:
        key = f"{kind}:{name.lower()}"
        if key in entities:
            ent = entities[key]
            if role == "attendee":
                ent.role = "attendee"
            if email and not ent.email:
                ent.email = email
            return ent.ref
        ref = f"{kind[0]}{len(entities) + 1}"
        entities[key] = ExtractedEntity(ref=ref, kind=kind, name=name, role=role, email=email)  # type: ignore[arg-type]
        return ref

    if owner_name:
        ref_for("person", owner_name, "attendee")

    for match in ATTENDEES_RE.finditer(text):
        for raw in _split_people(match.group(1)):
            email = None
            if m := NAME_EMAIL_RE.match(raw):
                raw, email = m.group("name").strip(), m.group("email").strip()
            elif m := EMAIL_RE.fullmatch(raw):
                continue
            org = None
            if m := NAME_ORG_RE.match(raw):
                raw, org = m.group("name").strip(), m.group("org").strip()
            if not raw or len(raw) > 80:
                continue
            person_ref = ref_for("person", raw, "attendee", email)
            if org:
                org_ref = ref_for("organization", org, "mentioned")
                relationships.append(
                    ExtractedRelationship(source=person_ref, target=org_ref, kind="works_at", context="attendee list")
                )

    for name, kind in known_entities or []:
        if kind not in ("person", "organization", "topic") or len(name) < 4:
            continue
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I):
            ref_for(kind, name, "mentioned")

    actions = [m.group(1).strip() for line in text.splitlines() if (m := ACTION_RE.match(line))]

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    first = lines[0].lstrip("# ").strip() if lines else ""
    derived_title = title or (first if 0 < len(first) <= 80 and not ATTENDEES_RE.match(first) else "Meeting notes")
    body = " ".join(
        ln for ln in lines if not ATTENDEES_RE.match(ln) and not ACTION_RE.match(ln) and ln.lstrip("# ") != first
    )
    sentences = re.split(r"(?<=[.!?])\s+", body)
    summary = " ".join(sentences[:3])[:600] or derived_title

    date_match = DATE_RE.search(text)
    has_attendees = any(e.role == "attendee" and e.name != owner_name for e in entities.values())
    return Extraction(
        doc_type="meeting_notes" if has_attendees or actions else "document",
        title=derived_title,
        occurred_on=occurred_on or (date_match.group(1) if date_match else None),
        summary=summary,
        action_items=actions,
        entities=list(entities.values()),
        relationships=relationships,
    )
