"""Import contact spreadsheets whose columns differ from file to file.

1. Map the columns onto CRM fields: the utility AI model reads the header and a few sample rows; without AI (or
   when it answers in a way that doesn't fit the sheet), header synonyms are used.
2. Import the rows the same way every time: find or create the people and organizations, add works_at, knows and
   attended lines, tags, and a note per row. Nothing here is guessed by an AI: given the same mapping, the same
   rows make the same records.

Rules from DynaCRM that tests pin: placeholders ("na", "–", "?") are not names; a row can be an organization;
"Heather" at an organization is the "Heather Quinn" already there (matched by record, not by spelling), and a
first name arriving before the full name is upgraded; an existing value is never overwritten.
"""
import logging
import re
import sqlite3
from datetime import date, datetime, time, timezone
from typing import Literal

from dateutil import parser as dateparser
from pydantic import BaseModel, Field

from core.server import ai

from . import resolve, roles, store
from .documents import ParsedSheet
from .model import Entity

log = logging.getLogger("crm.spreadsheets")

Target = Literal[
    "name", "first_name", "last_name", "organization", "title", "email", "phone", "linkedin_url",
    "website", "location", "contact_info", "met_with", "relationship_strength", "last_contact",
    "tags", "note", "attribute", "ignore",
]


class ColumnMap(BaseModel):
    column: str = Field(description="Header text exactly as given.")
    target: Target
    attribute_key: str | None = Field(default=None, description="snake_case key when target is 'attribute'.")


class SheetMapping(BaseModel):
    header_row: int = Field(description="1-based row number (as shown) of the header row.")
    row_kind: Literal["person", "organization", "skip"] = Field(
        description="What each data row describes. skip: not a list of contacts (e.g. a single contact card or a summary)."
    )
    columns: list[ColumnMap]
    sheet_tags: list[str] = Field(default_factory=list, description="0-3 tags every row should get, e.g. the event or group they came from.")
    event_name: str | None = Field(default=None, description="If the rows are people met at one event, its name.")
    event_date: str | None = Field(default=None, description="That event's date as YYYY-MM-DD if known.")
    reason: str = Field(default="", description="One short sentence.")


MAPPING_SYSTEM = """You map the columns of a contact spreadsheet onto CRM fields.

Targets:
- name / first_name / last_name: the person's (or organization's) name.
- organization: employer or organization; title: job title / role / occupation.
- email, phone, linkedin_url, website, location (city or physical address).
- contact_info: a mixed column that may hold an email, a LinkedIn URL or a phone number.
- met_with: which of the owner's team met this contact (names like "Sam", "Mickey").
- relationship_strength: a 1-5 score. last_contact: date of last contact.
- tags: short categorical values worth tagging (category, contact type, sector, "met at" venue).
- note: free-text worth keeping (conversation summary, why useful, details, next action, interest level, status).
- attribute: a short structured value worth keeping on the record (give attribute_key in snake_case).
- ignore: checkboxes, links to internal docs, empty or redundant columns.
Map every column. Use row_kind "skip" for sheets that are not a list of contacts."""

SYNONYMS: dict[str, list[str]] = {
    "name": ["name", "full name", "contact", "contact name", "person"],
    "first_name": ["first name", "first", "given name"],
    "last_name": ["last name", "last", "surname", "family name"],
    "organization": ["organization", "organisation", "company", "org", "employer", "firm"],
    "title": ["role", "title", "position", "occupation", "job title"],
    "email": ["email", "e-mail", "email address", "email addresses"],
    "phone": ["phone", "mobile", "cell", "phone number"],
    "linkedin_url": ["linkedin", "linkedin url", "linkedin profile"],
    "website": ["website", "url", "site"],
    "location": ["location", "city", "address", "physical address"],
    "contact_info": ["contact info", "contact information", "contact details"],
    "met_with": ["met with", "owner", "point person", "who met"],
    "relationship_strength": ["relationship strength", "strength", "relationship strength (1-5)"],
    "last_contact": ["last contact", "last contacted", "last touch"],
    "tags": ["category", "type", "contact type", "sector", "industry", "tags", "met at"],
    "ignore": ["done", "mailed", "link to doc", "personal file"],
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PLACEHOLDERS = {"na", "n/a", "n.a.", "none", "null", "nil", "?", "??", "tbd", "unknown", "x", "no", "same"}
# Category values that mean "this row is an organization, not a person".
ORG_CATEGORIES = {"organization", "organisation", "company", "program", "programme", "institution", "nonprofit", "foundation", "agency"}
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:[\w-]+\.)?linkedin\.com/[^\s,;]+", re.I)
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
ORG_MATCH_THRESHOLD = 0.85


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:40]


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\(.*?\)|[:?]", "", h.lower())).strip()


def heuristic_mapping(sheet: ParsedSheet) -> SheetMapping:
    best_row, best_hits = 0, 0
    for i, row in enumerate(sheet.rows[:5]):
        hits = sum(1 for c in row if any(_norm_header(c) == s or _norm_header(c).startswith(s) for syns in SYNONYMS.values() for s in syns))
        if hits > best_hits:
            best_row, best_hits = i, hits
    if best_hits < 2:
        return SheetMapping(header_row=1, row_kind="skip", columns=[], reason="No recognisable header row")
    columns = []
    for header in sheet.rows[best_row]:
        if not header:
            continue
        norm = _norm_header(header)
        target = next((t for t, syns in SYNONYMS.items() if norm in syns), None)
        target = target or next((t for t, syns in SYNONYMS.items() if any(norm.startswith(s) for s in syns)), None)
        columns.append(ColumnMap(column=header, target=target or "note"))  # type: ignore[arg-type]
    return SheetMapping(header_row=best_row + 1, row_kind="person", columns=columns, reason="Matched header names")


def mapping_prompt(filename: str, sheet: ParsedSheet, owner: str | None, team: list[str]) -> str:
    lines = [f"File: {filename}", f"Sheet: {sheet.name}"]
    if owner:
        lines.append(f"CRM owner: {owner}. Team: {', '.join(team) or '-'}.")
    lines.append("First rows (row number: cells separated by ' | '):")
    for i, row in enumerate(sheet.rows[:8], 1):
        lines.append(f"{i}: " + " | ".join(c[:60] for c in row))
    return "\n".join(lines)


def map_sheet(filename: str, sheet: ParsedSheet, owner: str | None, team: list[str]) -> tuple[SheetMapping, str]:
    """(mapping, how): how is "anthropic:model" and so on, or "rules". A provider-wide failure raises ai.AIError
    (provider_down) instead of quietly falling back: every sheet would be mapped by guesswork."""
    if roles.choice("utility") != "rules":
        try:
            mapping, pid = roles.structured("utility", mapping_prompt(filename, sheet, owner, team), MAPPING_SYSTEM,
                                            SheetMapping, 8000)
            headers = set(sheet.rows[mapping.header_row - 1]) if 0 < mapping.header_row <= len(sheet.rows) else set()  # type: ignore[attr-defined]
            if mapping.row_kind == "skip" or any(c.column in headers for c in mapping.columns):  # type: ignore[attr-defined]
                return mapping, f"{pid}:{ai.describe(pid)['model']}"  # type: ignore[return-value]
            log.warning("AI mapping for %s/%s named headers that aren't there; using rules", filename, sheet.name)
        except ai.AIError as e:
            if e.provider_down:
                raise
            log.warning("AI column mapping failed for %s/%s: %s", filename, sheet.name, e)
    return heuristic_mapping(sheet), "rules"


def _clean(value: str) -> str | None:
    """Drop placeholders ("na", "?", "–") and cells with no letters or digits."""
    v = value.strip()
    if not v or v.lower() in PLACEHOLDERS or not re.search(r"[^\W_]", v):
        return None
    return v


def _looks_like_contact(value: str) -> bool:
    v = value.strip()
    return bool(EMAIL_RE.fullmatch(v) or re.fullmatch(r"\+?[\d\s().-]{7,}", v))


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return dateparser.parse(value, default=datetime(2000, 1, 1)).date()
    except (ValueError, OverflowError):
        return None


def _noon(day: date) -> datetime:
    return datetime.combine(day, time(12), tzinfo=timezone.utc)


class SheetImporter:
    """Imports sheets inside the caller's transaction (`c`). Nothing is visible to anyone until it commits."""

    def __init__(self, c: sqlite3.Connection, owner: Entity | None, team: list[Entity], source: str):
        self.c = c
        self.owner = owner
        self.team = team
        self.source = source
        self.made: dict[str, Entity] = {}   # records created in this import, latest state (the match index can't see them yet)
        self.stats = {"rows": 0, "people_created": 0, "people_updated": 0, "orgs_created": 0,
                      "relationships": 0, "notes": 0, "skipped_rows": 0}

    # ---- finding and making records ----

    def _row(self, row: sqlite3.Row | None) -> Entity | None:
        return store._entity(row) if row else None

    def _by_exact(self, kind: str, name: str | None, email: str | None, linkedin: str | None) -> Entity | None:
        c = self.c
        if email:
            e = self._row(c.execute("SELECT * FROM crm_entities WHERE kind = ? AND lower(json_extract(attributes, '$.email')) = ? LIMIT 1",
                                    (kind, email.lower())).fetchone())
            if e:
                return e
        if linkedin:
            e = self._row(c.execute(
                "SELECT * FROM crm_entities WHERE kind = ? AND rtrim(lower(json_extract(attributes, '$.linkedin_url')), '/') = ? LIMIT 1",
                (kind, linkedin.lower().rstrip("/"))).fetchone())
            if e:
                return e
        if name:
            rows = c.execute("SELECT * FROM crm_entities WHERE kind = ? AND lower(name) = ?", (kind, name.lower())).fetchall()
            if len(rows) == 1:
                return self._row(rows[0])
            return self._row(c.execute(
                "SELECT e.* FROM crm_entities e, json_each(COALESCE(json_extract(e.attributes, '$.aliases'), '[]')) a "
                "WHERE e.kind = ? AND lower(a.value) = ? LIMIT 1", (kind, name.lower())).fetchone())
        return None

    def _same_first_name_at(self, name: str, org: Entity) -> Entity | None:
        """"Heather" at ORTADA and "Heather Quinn" at ORTADA are the same person."""
        first = name.split()[0].lower()
        rows = self.c.execute(
            "SELECT DISTINCT p.id, p.name FROM crm_entities p JOIN crm_relationships r ON r.source_id = p.id AND r.kind = 'works_at' "
            "WHERE p.kind = 'person' AND r.target_id = ? AND (lower(p.name) = ? OR lower(p.name) LIKE ? || ' %')",
            (org.id, first, first)).fetchall()
        full = " " in name.strip()
        rows = [r for r in rows if (" " in r["name"]) != full]   # pair a first-name-only record with a full name, never two full names
        if len(rows) != 1:
            return None
        found = store.get_entity(rows[0]["id"], self.c)
        if full and found is not None and " " not in found.name:
            aliases = sorted(set((found.attributes or {}).get("aliases") or []) | {found.name})
            found = store.update_entity(found.id, conn=self.c, name=name[:300], attributes={**(found.attributes or {}), "aliases": aliases})
            if found.id in self.made:
                self.made[found.id] = found
        return found

    def _make(self, kind: str, name: str, **fields) -> Entity:
        e = store.create_entity(kind, name[:300], source=self.source, conn=self.c, **fields)
        self.made[e.id] = e
        return e

    def person(self, name: str, email: str | None, linkedin: str | None, org: Entity | None = None) -> Entity:
        found = self._by_exact("person", name, email, linkedin)
        if not found and org is not None:
            found = self._same_first_name_at(name, org)
        if found:
            return found
        self.stats["people_created"] += 1
        return self._make("person", name)

    def organization(self, name: str) -> Entity:
        found = self._by_exact("organization", name, None, None)
        if not found:
            match, _ = resolve.pick_match(resolve.find_candidates("organization", name, extra=list(self.made.values())), ORG_MATCH_THRESHOLD)
            found = match.entity if match else None
        if found:
            return found
        self.stats["orgs_created"] += 1
        return self._make("organization", name)

    def teammate(self, token: str) -> Entity | None:
        t = token.strip().lower()
        if not t:
            return None
        for p in self.team:
            full = p.name.lower()
            if t == full or t == full.split()[0] or (p.attributes or {}).get("nickname", "").lower() == t:
                return p
            if any(t == a.lower() or t == a.lower().split()[0] for a in (p.attributes or {}).get("aliases", [])):
                return p
        return None

    def edge(self, s: Entity, t: Entity, kind: str, **kw) -> None:
        if s.id == t.id:
            return
        _, created = store.upsert_edge(s.id, t.id, kind, conn=self.c, source=self.source, **kw)
        self.stats["relationships"] += int(created)

    # ---- importing ----

    def import_sheet(self, sheet: ParsedSheet, mapping: SheetMapping, file_tag: str | None) -> None:
        if mapping.row_kind == "skip" or not (0 < mapping.header_row <= len(sheet.rows)):
            return
        header = sheet.rows[mapping.header_row - 1]
        index = {h: i for i, h in enumerate(header) if h}
        cols = [(c, index[c.column]) for c in mapping.columns if c.column in index and c.target != "ignore"]
        base_tags = [slug(t) for t in mapping.sheet_tags if slug(t)] + ([file_tag] if file_tag else [])

        event = None
        if mapping.event_name:
            event_day = _parse_date(mapping.event_date or "")
            event = self._by_exact("meeting", mapping.event_name, None, None)
            if event is None:
                event = self._make("meeting", mapping.event_name, tags=base_tags, attributes={"event": True},
                                   occurred_at=_noon(event_day) if event_day else None)
            if self.owner:
                self.edge(self.owner, event, "attended")

        for row in sheet.rows[mapping.header_row:]:
            if row == header or not any(row):
                continue
            self._import_row(row, cols, mapping, base_tags, event)

    def _import_row(self, row, cols, mapping: SheetMapping, base_tags: list[str], event: Entity | None) -> None:
        get: dict[str, list[tuple[str, str]]] = {}
        for c, i in cols:
            v = _clean(row[i]) if i < len(row) else None
            if v:
                get.setdefault(c.target, []).append((c.column, v) if c.target != "attribute" else (c.attribute_key or slug(c.column), v))

        def first(target: str) -> str | None:
            return get[target][0][1] if target in get else None

        name = first("name") or " ".join(x for x in (first("first_name"), first("last_name")) if x)
        email, linkedin, phone = first("email"), first("linkedin_url"), first("phone")
        for _, v in get.get("contact_info", []):
            email = email or (m.group(0) if (m := EMAIL_RE.search(v)) else None)
            linkedin = linkedin or (m.group(0) if (m := LINKEDIN_RE.search(v)) else None)
            phone = phone or (m.group(0) if (m := PHONE_RE.search(v)) else None)
        if email and not EMAIL_RE.fullmatch(email.strip()):
            email = (m.group(0) if (m := EMAIL_RE.search(email)) else None)
        if linkedin and not LINKEDIN_RE.search(linkedin):
            linkedin = None
        if linkedin and not linkedin.startswith("http"):
            linkedin = "https://" + linkedin
        header_names = {c.column.lower() for c in mapping.columns}
        org_name = first("organization")
        categories = {slug(t) for _, v in get.get("tags", []) for t in re.split(r"[,;/]", v)}
        if name and _looks_like_contact(name):
            name = ""  # a stray email or phone number in the name column is not a person
        is_org = (
            mapping.row_kind == "organization"
            or bool(categories & ORG_CATEGORIES)
            or bool(name and org_name and name.lower() == org_name.lower())
            or bool(not name and org_name)
        )
        if is_org:
            name = name or org_name or ""
        if not name or name.lower() in header_names:
            self.stats["skipped_rows"] += 1
            return
        self.stats["rows"] += 1

        # Resolve the employer first: its record (not its spelling) identifies colleagues.
        org = self.organization(org_name) if org_name and org_name.lower() != name.lower() else None
        entity = self.organization(name) if is_org else self.person(name, email, linkedin, org)

        before = dict(entity.attributes or {})
        attrs = dict(before)
        for key, value in (("email", email), ("linkedin_url", linkedin), ("phone", phone),
                           ("title", None if is_org else first("title")),
                           ("location", first("location")), ("website", first("website"))):
            if value and not attrs.get(key):
                attrs[key] = value[:300]
        for key, value in get.get("attribute", []):
            attrs.setdefault(key, value[:300])
        last_contact = _parse_date(first("last_contact") or "")
        if last_contact:
            attrs["last_contact"] = last_contact.isoformat()

        tags = list(base_tags)
        for _, v in get.get("tags", []):
            tags += [slug(t) for t in re.split(r"[,;/]", v) if slug(t) and slug(t) not in ORG_CATEGORIES]
        if is_org and first("title"):
            tags.append(slug(first("title")))  # e.g. an organization's "Role: Sponsor"
        new_tags = list(dict.fromkeys([*(entity.tags or []), *tags]))[:20] if tags else list(entity.tags or [])

        fields: dict = {}
        if attrs != before:
            fields["attributes"] = attrs
            if entity.id not in self.made and entity.kind == "person":
                self.stats["people_updated"] += 1
        if new_tags != list(entity.tags or []):
            fields["tags"] = new_tags
        if fields:
            entity = store.update_entity(entity.id, conn=self.c, **fields)
            if entity.id in self.made:
                self.made[entity.id] = entity

        if org is not None and org.id != entity.id:
            if is_org:
                self.edge(entity, org, "part_of")
            else:
                self.edge(entity, org, "works_at", properties={"title": first("title")} if first("title") else None)

        strength = None
        if (raw := first("relationship_strength")) is not None:
            try:
                strength = int(round(float(raw)))
            except ValueError:
                strength = None
            if strength is not None and not 1 <= strength <= 5:
                strength = None

        met = [self.teammate(t) for _, v in get.get("met_with", []) for t in re.split(r",|/|&|\band\b", v)]
        met = [m for m in met if m]
        if entity.kind == "person":
            for mate in met:
                self.edge(mate, entity, "knows", strength=strength if mate is self.owner else None,
                          properties={"context": "met in person"})
            if self.owner and self.owner not in met:
                self.edge(self.owner, entity, "knows", strength=strength or 2)
            if event:
                self.edge(entity, event, "attended")
                for mate in met:
                    self.edge(mate, event, "attended")

        note_lines = [f"{col}: {v}" for col, v in get.get("note", [])]
        if note_lines:
            when = last_contact or (event.occurred_at.date() if event and event.occurred_at else None)
            store.add_note(entity.id, "\n".join(note_lines), source=self.source, evidence_id=event.id if event else None,
                           occurred_at=_noon(when) if when else None, conn=self.c)
            self.stats["notes"] += 1
