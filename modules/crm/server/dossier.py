"""What's on file about one person, for AI elsewhere in the app: the "people.dossier" offer, and the CRM's part of
the host's people directory.

Another module (Sediment) never reads these tables; it asks `family.call("people.dossier", id=…)`, which this app
answers in-process (and another family app on this Mac could ask over localhost with the family token). The answer is
plain data: the overview's records about the person (profiles.records), the key points of recent meetings, and,
when there's a subject, passages that mention it, cut from the person's notes and from the notes and transcripts of
the meetings they were in. With `voice`, it also carries lines they said themselves in those transcripts.

Granola labels speakers "Me" and "Them" (or a diarization label); in a meeting of just you and them, "Them" is them.
"""
import hashlib
import json
import re
from datetime import date, datetime

from . import profiles, store, views
from .connections import sort_key
from .model import Entity

OFFER = "people.dossier"
WINDOW = 400                                    # characters kept either side of a mention
PASSAGES = {"local": 8_000, "cloud": 40_000}    # the most passage text sent along
VOICE = {"local": 4_000, "cloud": 15_000}       # the most of their own lines
PER_MEETING = {"local": 1_500, "cloud": 6_000}  # their lines from any one meeting, for the subject "you"
KEY_POINT_MEETINGS = 8
TRANSCRIPT = "## Transcript"
SPEAKER = re.compile(r"^([^:\n]{1,60}):\s+(.+)$")


def _day(d: date | datetime | None) -> str:
    return d.strftime("%Y-%m-%d") if d else "undated"


def _canonical(raw: str) -> str:
    """The record an id stands for now: "crm:" taken off, and merges followed."""
    eid = (raw or "").removeprefix("crm:").strip()
    if not eid:
        raise LookupError("Say which person")
    if store.get_entity(eid) is None and (now := store.merged_into(eid)):
        return now
    return eid


def _first(name: str) -> str:
    return name.split()[0] if name.split() else name


def _names(e: Entity) -> list[str]:
    """How someone or something might be written: the name, other names on file, and a person's first name."""
    names = [e.name, *((e.attributes or {}).get("aliases") or [])]
    if e.kind == "person" and len(_first(e.name)) >= 3:
        names.append(_first(e.name))
    return _unique(names)


def _unique(words: list[str]) -> list[str]:
    seen, out = set(), []
    for w in (w.strip() for w in words if w):
        if w and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return out


def _pattern(terms: list[str]) -> re.Pattern | None:
    terms = [t for t in _unique(terms) if len(t) >= 2]
    if not terms:
        return None
    alts = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)", re.IGNORECASE)


def windows(text: str, pattern: re.Pattern, width: int = WINDOW) -> list[str]:
    """The stretches of `text` around each match, overlapping ones joined, cut at spaces, with … where cut."""
    spans: list[list[int]] = []
    for m in pattern.finditer(text):
        start, end = max(0, m.start() - width), min(len(text), m.end() + width)
        if spans and start <= spans[-1][1]:
            spans[-1][1] = end
        else:
            spans.append([start, end])
    out = []
    for start, end in spans:
        if start > 0 and (space := text.find(" ", start, start + 40)) != -1:
            start = space + 1
        if end < len(text) and (space := text.rfind(" ", end - 40, end)) != -1:
            end = space
        piece = " ".join(text[start:end].split())
        out.append(("…" if start > 0 else "") + piece + ("…" if end < len(text) else ""))
    return out


def _transcript_lines(body: str) -> list[tuple[str, str]]:
    at = body.find(TRANSCRIPT)
    if at < 0:
        return []
    lines = []
    for line in body[at + len(TRANSCRIPT):].splitlines():
        if m := SPEAKER.match(line.strip()):
            lines.append((m.group(1).strip(), m.group(2).strip()))
    return lines


class _Book:
    """One person's meetings and notes, newest first, read once per answer."""

    def __init__(self, v: views.Views, p: Entity):
        self.v, self.p = v, p
        me = v.me.id if v.me else None
        ix, ents = v.ix, v.snap.entities
        self.meetings = sorted(
            (ents[mid] for mid, present in ix.attendees.items() if p.id in present and ents[mid].kind == "meeting"),
            key=lambda e: e.occurred_at.timestamp() if e.occurred_at else 0.0, reverse=True)
        self.with_me = {m.id for m in self.meetings if me and me in ix.attendees.get(m.id, set())}
        self.one_to_one = {m.id for m in self.meetings if me and ix.attendees.get(m.id, set()) == {p.id, me}}
        self._notes: dict[str, list] = {}

    def notes(self, eid: str) -> list:
        if eid not in self._notes:
            self._notes[eid] = store.notes_of(eid)
        return self._notes[eid]

    def their_lines(self, meeting: Entity) -> list[str]:
        """What they said in one meeting's transcripts: lines under their name, or "Them" when it was just the two of you."""
        names = {n.lower() for n in _names(self.p)}
        if meeting.id in self.one_to_one:
            names.add("them")
        out = []
        for n in self.notes(meeting.id):
            out += [text for who, text in _transcript_lines(n.body) if who.lower() in names]
        return out


def _key_points(book: _Book) -> str:
    lines = []
    for m in book.meetings[:KEY_POINT_MEETINGS]:
        points = [str(x).strip() for x in (m.attributes or {}).get("key_points") or [] if str(x).strip()]
        if points:
            lines.append(f"- {_day(m.occurred_at)}, {m.name}: " + "; ".join(points))
    return "\n".join(lines)


def _passages(book: _Book, pattern: re.Pattern | None, me: bool, transcripts: bool, scale: str) -> list[dict]:
    """Dated stretches that bear on the subject, newest first, within the budget."""
    budget, out = PASSAGES[scale], []

    def add(when, source: str, text: str) -> bool:
        nonlocal budget
        if budget <= 0:
            return False
        text = text[:budget]
        out.append({"date": _day(when), "source": source, "text": text})
        budget -= len(text) + 40
        return True

    if me:
        # Toward you: what they said in the meetings you were both in.
        for m in book.meetings:
            if m.id not in book.with_me:
                continue
            if transcripts and (lines := book.their_lines(m)):
                said = " / ".join(lines)[:PER_MEETING[scale]]
                if not add(m.occurred_at, f"What they said in “{m.name}”", said):
                    break
            elif (m.summary or "").strip():
                if not add(m.occurred_at, f"Summary of “{m.name}”", m.summary.strip()):
                    break
        return out

    if pattern is None:
        return out
    sources: list[tuple] = [(n.occurred_at, "Your notes on them", n.body) for n in book.notes(book.p.id)]
    for m in book.meetings:
        if (m.summary or "").strip():
            sources.append((m.occurred_at, f"Summary of “{m.name}”", m.summary))
        if transcripts:
            sources += [(m.occurred_at, f"Notes and transcript of “{m.name}”", n.body) for n in book.notes(m.id)]
    sources.sort(key=lambda s: s[0].timestamp() if s[0] else 0.0, reverse=True)
    for when, source, text in sources:
        for piece in windows(text, pattern):
            if not add(when, source, piece):
                return out
    return out


def _voice(book: _Book, scale: str) -> list[dict]:
    budget, out = VOICE[scale], []
    for m in book.meetings:
        for line in book.their_lines(m):
            if budget <= 0:
                return out
            line = line[:budget]
            out.append({"date": _day(m.occurred_at), "meeting": m.name, "text": line})
            budget -= len(line) + 30
    return out


def _subject(v: views.Views, about: dict) -> tuple[dict | None, list[str]]:
    """What the reading is about, and the words that mark it in the records."""
    kind = about.get("kind") or ""
    if kind == "me":
        return ({"kind": "me", "name": v.me.name if v.me else "You", "summary": None}, [])
    terms = [str(t) for t in about.get("terms") or []]
    if about.get("ref"):
        eid = _canonical(str(about["ref"]))
        e = v.snap.entities.get(eid)
        if e is None:
            raise LookupError("The subject isn't in your book any more")
        return ({"kind": e.kind, "ref": f"crm:{e.id}", "name": e.name, "aliases": (e.attributes or {}).get("aliases") or [],
                 "summary": (e.summary or "").strip() or None}, _names(e) + terms)
    if about.get("name"):
        return ({"kind": kind or "product", "name": str(about["name"]), "summary": about.get("summary")},
                [str(about["name"]), *terms])
    return None, terms


def handle(args: dict) -> dict:
    """The offer. Args: id, scale ("local" | "cloud"), about ({kind: "me"} | {ref} | {kind, name, terms, summary}),
    transcripts (bool), voice (bool). Raises LookupError for no such person, ValueError for you."""
    v = views.get()
    eid = _canonical(str(args.get("id") or ""))
    p = v.snap.entities.get(eid)
    if p is None or p.kind != "person":
        raise LookupError("That person isn't in your book")
    if p.is_self:
        raise ValueError("This is for people other than you")
    scale = "local" if args.get("scale") == "local" else "cloud"
    transcripts = bool(args.get("transcripts", True))
    text, material = profiles.records(v, p, scale == "local")
    book = _Book(v, p)
    subject, terms = _subject(v, args.get("about") or {})
    me = bool(subject and subject["kind"] == "me")
    company = v.employer(v.me.id) if v.me else None
    out = {
        "ref": f"crm:{p.id}", "id": p.id, "name": p.name, "first": _first(p.name),
        "owner": profiles._about_me(v), "records": text, "material": material,
        "key_points": _key_points(book), "subject": subject,
        "passages": _passages(book, _pattern(terms), me, transcripts, scale) if subject else [],
        "voice": _voice(book, scale) if args.get("voice") and transcripts else [],
        "meetings_with_you": len(book.with_me),
        "company": {"ref": f"crm:{company.id}", "name": company.name} if company else None,
    }
    out["fingerprint"] = hashlib.sha256(json.dumps(out, sort_keys=True, default=str).encode()).hexdigest()[:24]
    return out


# ── The people directory ──────────────────────────────────────────────

def people(q: str, limit: int) -> list[dict]:
    """The CRM's part of the host's people directory (Module.people): the people you know best first, or the ones whose
    name or another name starts a word with what was typed."""
    v = views.get()
    q = (q or "").strip().lower()
    found = []
    for p in v.snap.of_kind("person"):
        if q and not any(w.startswith(q) or n.lower().startswith(q)
                         for n in _names(p) for w in n.lower().split()):
            continue
        found.append(p)
    found.sort(key=lambda p: (not p.is_self, *(sort_key(v.conns[p.id], p.name) if p.id in v.conns else (1, 0.0, p.name.lower()))))
    return [{"id": p.id, "name": p.name, "email": (p.attributes or {}).get("email"), "detail": v.summary(p.id).subtitle,
             "is_self": p.is_self} for p in found[:limit]]
