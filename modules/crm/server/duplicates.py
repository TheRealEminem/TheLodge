"""Records that are probably the same person (or organization) twice, flagged for you to merge by hand.

A bulk import, a meeting transcript and a spreadsheet each spell people their own way, so "Jon Smith", "Jonathan
Smith" and "jon.smith@acme.example" turn into three records. This finds the likely pairs and says why. It never
merges anything itself: a merge moves meetings, notes and relationships from one record to another, and other
modules link to records, so it waits for your OK. Every merge can be undone (store.unmerge).

How a pair is judged, strongest first:
    same email, or the same LinkedIn profile          certain
    the same name, or one is the other's alias        very likely
    a nickname or short form with the same surname    likely ("Bob Lee" / "Robert Lee", "Chris" / "Christopher")
    a near-identical spelling                         likely ("Jordon Reyes" / "Jordan Reyes")
    a first name alone, and the full name, who share a meeting or an employer
Working at the same organization adds to the score. For organizations: the same website, the same name once
"Inc", "LLC" and the like are taken off, or a near-identical spelling.

    crm_duplicates   a_id < b_id, score, reasons, status open | not_same (tables are in store.py)
"""
import json
import re
import unicodedata
from collections import defaultdict
from itertools import combinations
from urllib.parse import urlparse

from core.server import db, events, jobs

from . import resolve, snapshot, store
from .model import Entity

FLAG = 0.75
CHECK_SECONDS = 300
MAX_BLOCK = 400      # a group this big (a very common first name) is too vague to compare within

_HONORIFICS = {"dr", "mr", "mrs", "ms", "miss", "mx", "prof", "sir", "dame", "jr", "sr", "ii", "iii", "iv", "phd", "md",
               "mba", "esq", "cpa"}
_LEGAL = {"inc", "incorporated", "llc", "ltd", "limited", "co", "corp", "corporation", "company", "plc", "gmbh", "sa",
          "ag", "bv", "pty", "lp", "llp", "pbc", "the"}
_NICKNAMES = [
    {"robert", "rob", "bob", "bobby", "robbie"}, {"william", "will", "bill", "billy", "liam"},
    {"elizabeth", "liz", "beth", "betsy", "eliza", "lizzie"}, {"james", "jim", "jimmy", "jamie"},
    {"michael", "mike", "mikey", "mick"}, {"thomas", "tom", "tommy"}, {"anthony", "tony"}, {"david", "dave", "davey"},
    {"daniel", "dan", "danny"}, {"christopher", "chris", "kit"}, {"christina", "christine", "chris", "tina"},
    {"katherine", "catherine", "kathryn", "kate", "katie", "kathy", "cathy", "kat"}, {"jennifer", "jen", "jenny"},
    {"alexander", "alex", "sasha", "xander"}, {"alexandra", "alex", "lexi", "sasha"}, {"samuel", "sam", "sammy"},
    {"samantha", "sam"}, {"matthew", "matt"}, {"nicholas", "nick", "nicky"}, {"benjamin", "ben", "benny"},
    {"joseph", "joe", "joey"}, {"stephen", "steven", "steve"}, {"richard", "rick", "rich", "dick", "ricky"},
    {"andrew", "andy", "drew"}, {"patrick", "pat", "paddy"}, {"patricia", "pat", "patty", "trish"},
    {"gregory", "greg"}, {"jeffrey", "geoffrey", "jeff", "geoff"}, {"edward", "ed", "eddie", "ted", "ned"},
    {"joshua", "josh"}, {"jonathan", "jon", "john", "johnny", "jack"}, {"margaret", "maggie", "meg", "peggy", "margo"},
    {"susan", "sue", "suzy"}, {"abigail", "abby"}, {"rebecca", "becky", "becca"}, {"nathan", "nathaniel", "nate"},
    {"zachary", "zach", "zack"}, {"timothy", "tim", "timmy"}, {"kenneth", "ken", "kenny"}, {"lawrence", "larry"},
    {"charles", "charlie", "chuck", "chas"}, {"victoria", "vicky", "tori"}, {"deborah", "debra", "deb", "debbie"},
    {"pamela", "pam"}, {"jacqueline", "jackie"}, {"frederick", "fred", "freddie"}, {"ronald", "ron", "ronnie"},
    {"donald", "don", "donnie"}, {"raymond", "ray"}, {"gerald", "gerry", "jerry"}, {"philip", "phillip", "phil"},
    {"douglas", "doug"}, {"leonard", "leo", "len", "lenny"}, {"theodore", "theo", "ted", "teddy"},
    {"elena", "lena"}, {"natalie", "nat"}, {"isabel", "isabelle", "izzy", "bella"}, {"emily", "em", "emmy"},
]
_NICK = defaultdict(set)
for group in _NICKNAMES:
    for name in group:
        _NICK[name] |= group

_state: dict = {}


# ── Names ─────────────────────────────────────────────────────────────

def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def name_words(name: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", _plain(re.sub(r"\([^)]*\)", " ", name)))
    return [w for w in words if w not in _HONORIFICS]


def org_words(name: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", _plain(name.replace("&", " and "))) if w not in _LEGAL]


def _first_names_match(a: str, b: str) -> bool:
    """The same first name, a short form of it ("Chris", "Christopher") or a known nickname ("Bob", "Robert")."""
    if a == b:
        return True
    if len(a) == 1 or len(b) == 1:
        return a[0] == b[0]
    short, long_ = sorted((a, b), key=len)
    return (len(short) >= 3 and long_.startswith(short)) or b in _NICK.get(a, ())


def _edits(a: str, b: str) -> int:
    """Levenshtein distance, with swapped neighbours counting as one."""
    prev2, prev = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
            if prev2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def _slip(a: str, b: str, shortest: int = 4) -> bool:
    """A misspelling of the same word: one letter off ("Nair" / "Nayr"), two in a long word. Short words are left
    alone ("Jon" and "Jen", "John" and "Joan" are different people)."""
    if a == b or min(len(a), len(b)) < shortest:
        return False
    return _edits(a, b) <= (2 if min(len(a), len(b)) >= 8 else 1)


def _linkedin(url: str | None) -> str | None:
    if not url:
        return None
    path = urlparse(url if "//" in url else f"https://{url}").path.strip("/").lower()
    m = re.match(r"(?:in|pub)/([^/?#]+)", path)
    return m.group(1) if m else None


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url if "//" in url else f"https://{url}").netloc.lower().split(":")[0]
    return host.removeprefix("www.") or None


# ── Judging a pair ────────────────────────────────────────────────────

class _Facts:
    """What the finder knows about everyone, built once per pass."""

    def __init__(self, snap: snapshot.Snapshot):
        self.snap = snap
        self.employers: dict[str, set[str]] = defaultdict(set)
        self.meetings: dict[str, set[str]] = defaultdict(set)
        for e in snap.edges:
            if e.kind == "works_at":
                self.employers[e.source_id].add(e.target_id)
            elif e.kind == "attended":
                self.meetings[e.source_id].add(e.target_id)

    def name(self, eid: str) -> str:
        return self.snap.entities[eid].name


def _aliases(e: Entity, words) -> set[tuple[str, ...]]:
    return {tuple(words(a)) for a in (e.attributes or {}).get("aliases") or [] if words(a)}


def judge_people(a: Entity, b: Entity, facts: _Facts) -> tuple[float, list[str]]:
    aa, ba = a.attributes or {}, b.attributes or {}
    score, reasons = 0.0, []

    def hit(s: float, why: str) -> None:
        nonlocal score
        score = max(score, s)
        reasons.append(why)

    if aa.get("email") and str(aa["email"]).strip().lower() == str(ba.get("email") or "").strip().lower():
        hit(1.0, f"Same email ({aa['email']})")
    if (la := _linkedin(aa.get("linkedin_url"))) and la == _linkedin(ba.get("linkedin_url")):
        hit(1.0, "Same LinkedIn profile")
    wa, wb = name_words(a.name), name_words(b.name)
    if not wa or not wb:
        return score, reasons
    if wa == wb:
        hit(0.95, "Same name")
    elif tuple(wa) in _aliases(b, name_words) or tuple(wb) in _aliases(a, name_words):
        hit(0.95, "One is also written as the other")
    elif len(wa) > 1 and len(wb) > 1:
        if wa[-1] == wb[-1] and _first_names_match(wa[0], wb[0]):
            hit(0.8, f"“{wa[0].title()}” and “{wb[0].title()}” can be the same first name")
        elif len(wa) == len(wb) and sum(x != y for x, y in zip(wa, wb)) == 1 \
                and all(x == y or _slip(x, y, 5 if i == 0 else 4) for i, (x, y) in enumerate(zip(wa, wb))):
            hit(0.8, "Almost the same spelling")
    else:
        # A first name alone ("Priya") next to a full name ("Priya Nair"): only with something shared.
        short, full = (wa, wb) if len(wa) == 1 else (wb, wa)
        if _first_names_match(short[0], full[0]):
            together = facts.meetings[a.id] & facts.meetings[b.id]
            if together:
                hit(0.75, f"A first name alone, and in {len(together)} meeting{'s' if len(together) != 1 else ''} together")

    shared = facts.employers[a.id] & facts.employers[b.id]
    if score and shared:
        org = facts.name(next(iter(shared)))
        reasons.append(f"Both at {org}")
        score = min(1.0, score + 0.1)
    elif not score and shared and (len(wa) == 1) != (len(wb) == 1) and _first_names_match(wa[0], wb[0]):
        score = 0.75
        reasons.append(f"A first name alone, and both at {facts.name(next(iter(shared)))}")
    return score, reasons


def judge_orgs(a: Entity, b: Entity, facts: _Facts) -> tuple[float, list[str]]:
    aa, ba = a.attributes or {}, b.attributes or {}
    score, reasons = 0.0, []
    if (da := _domain(aa.get("website"))) and da == _domain(ba.get("website")):
        score = 1.0
        reasons.append(f"Same website ({da})")
    wa, wb = org_words(a.name), org_words(b.name)
    if wa and wa == wb:
        score = max(score, 0.95)
        reasons.append("Same name" if a.name.strip().lower() == b.name.strip().lower() else "Same name, apart from Inc, LLC and the like")
    elif wa and (tuple(wa) in _aliases(b, org_words) or tuple(wb) in _aliases(a, org_words)):
        score = max(score, 0.95)
        reasons.append("One is also written as the other")
    elif wa and wb and (sim := resolve.similarity(" ".join(wa), " ".join(wb))) >= 0.85 \
            and resolve._distinctive(a.name) & resolve._distinctive(b.name):
        score = max(score, round(sim, 2))
        reasons.append("Almost the same spelling")
    return score, reasons


# ── Finding pairs ─────────────────────────────────────────────────────

def _blocks(entities: list[Entity], kind: str) -> list[list[Entity]]:
    """Groups worth comparing within, so the work grows with the size of the groups, not the square of the book."""
    groups: dict[str, list[Entity]] = defaultdict(list)
    for e in entities:
        a = e.attributes or {}
        keys: set[str] = set()
        if a.get("email"):
            keys.add("e:" + str(a["email"]).strip().lower())
        if kind == "person":
            if li := _linkedin(a.get("linkedin_url")):
                keys.add("l:" + li)
            names = [name_words(e.name), *[name_words(x) for x in a.get("aliases") or []]]
            for words in names:
                if not words:
                    continue
                keys.add("n:" + " ".join(words))
                if len(words) > 1:
                    keys.add("s:" + words[-1])                       # same surname
                    keys.add(f"f:{words[0][:1]}:{words[-1][:2]}")    # spelling slips in the surname
                for first in {words[0], *_NICK.get(words[0], ())}:
                    keys.add("1:" + first)                            # first names, with nicknames
                    if len(first) >= 3:
                        keys.add("p:" + first[:3])                    # "Chris" / "Christopher"
        else:
            if d := _domain(a.get("website")):
                keys.add("d:" + d)
            for words in [org_words(e.name), *[org_words(x) for x in a.get("aliases") or []]]:
                if words:
                    keys.add("n:" + " ".join(words))
                    keys.add("w:" + words[0])
        for k in keys:
            groups[k].append(e)
    return [g for g in groups.values() if 1 < len(g) <= MAX_BLOCK]


def find(kinds: tuple[str, ...] = ("person", "organization")) -> list[dict]:
    """Every likely pair: {a_id, b_id, kind, score, reasons}, a_id < b_id."""
    snap = snapshot.load()
    facts = _Facts(snap)
    found: dict[tuple[str, str], dict] = {}
    for kind in kinds:
        judge = judge_people if kind == "person" else judge_orgs
        for group in _blocks(snap.of_kind(kind), kind):
            for x, y in combinations(group, 2):
                a, b = (x, y) if x.id < y.id else (y, x)
                if (a.id, b.id) in found or (a.is_self and b.is_self):
                    continue
                score, reasons = judge(a, b, facts)
                if score >= FLAG:
                    found[(a.id, b.id)] = {"a_id": a.id, "b_id": b.id, "kind": kind, "score": round(score, 3),
                                           "reasons": list(dict.fromkeys(reasons))}
    return list(found.values())


def refresh() -> dict:
    """Brings the flags up to date: new pairs added, ones that no longer look alike taken off. A pair you said is
    not the same stays that way."""
    pairs = find()
    now = db.now()
    known = {(r["a_id"], r["b_id"]): r for r in db.query("SELECT a_id, b_id, status FROM crm_duplicates")}
    added = 0
    with db.connect() as c:
        for p in pairs:
            row = known.pop((p["a_id"], p["b_id"]), None)
            if row is None:
                c.execute("INSERT INTO crm_duplicates (id, a_id, b_id, kind, score, reasons, created_at, updated_at) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (db.new_id(), p["a_id"], p["b_id"], p["kind"], p["score"], json.dumps(p["reasons"]), now, now))
                added += 1
            elif row["status"] == "open":
                c.execute("UPDATE crm_duplicates SET score = ?, reasons = ?, updated_at = ? WHERE a_id = ? AND b_id = ?",
                          (p["score"], json.dumps(p["reasons"]), now, p["a_id"], p["b_id"]))
        for (a, b), row in known.items():
            if row["status"] == "open":
                c.execute("DELETE FROM crm_duplicates WHERE a_id = ? AND b_id = ?", (a, b))
    if added:
        events.publish("crm.duplicates.changed", {"added": added})
    return {"pairs": len(pairs), "added": added}


def handle_check(job: jobs.Job) -> None:
    """The recurring check: only does the work when something in the book changed since the last one."""
    version = store.version()
    if _state.get("version") == version:
        return
    job.stage("Looking for duplicates")
    refresh()
    _state["version"] = version


def forget_check() -> None:
    """The next check looks again even if nothing changed (you asked to, or a merge was undone)."""
    _state.clear()


def seconds() -> int:
    return CHECK_SECONDS


# ── What you see and do ───────────────────────────────────────────────

def _pair(row: dict, people: dict) -> dict | None:
    a, b = people.get(row["a_id"]), people.get(row["b_id"])
    if a is None or b is None:
        return None
    return {"id": row["id"], "kind": row["kind"], "score": row["score"], "reasons": json.loads(row["reasons"]),
            "status": row["status"], "a": a, "b": b}


def listing(entity_id: str | None = None, limit: int = 100) -> dict:
    from . import views   # views builds on everything; imported late to keep this module light for the job

    if entity_id:
        rows = db.query("SELECT * FROM crm_duplicates WHERE status = 'open' AND (a_id = ? OR b_id = ?) ORDER BY score DESC",
                        (entity_id, entity_id))
    else:
        rows = db.query("SELECT * FROM crm_duplicates WHERE status = 'open' ORDER BY score DESC, updated_at DESC LIMIT ?", (limit,))
    total = db.one("SELECT count(*) AS n FROM crm_duplicates WHERE status = 'open'")["n"]
    v = views.get()
    ids = {r[k] for r in rows for k in ("a_id", "b_id")}
    cards = {}
    for eid in ids:
        e = v.snap.entities.get(eid)
        if e is None:
            continue
        employer = v.employer(eid) if e.kind == "person" else None
        cards[eid] = {"id": e.id, "name": e.name, "kind": e.kind, "is_self": e.is_self, "degree": len(v.snap.by_entity.get(eid, [])),
                      "subtitle": " at ".join(x for x in ((e.attributes or {}).get("title"), employer.name if employer else None) if x) or None,
                      "email": (e.attributes or {}).get("email"), "source": e.source,
                      "created_at": e.created_at.isoformat() if e.created_at else None}
    items = [p for r in rows if (p := _pair(r, cards))]
    return {"total": total, "items": items}


def not_same(pair_id: str) -> None:
    if not db.execute("UPDATE crm_duplicates SET status = 'not_same', updated_at = ? WHERE id = ?", (db.now(), pair_id)):
        raise store.NotFound("That pair isn't flagged any more")
    events.publish("crm.duplicates.changed", {})


def merge(pair_id: str, keep_id: str):
    """Your OK on a flagged pair: the other record is folded into the one you keep."""
    row = db.one("SELECT * FROM crm_duplicates WHERE id = ?", (pair_id,))
    if row is None:
        raise store.NotFound("That pair isn't flagged any more")
    if keep_id not in (row["a_id"], row["b_id"]):
        raise store.MergeError("Keep one of the two records in the pair")
    gone = row["b_id"] if keep_id == row["a_id"] else row["a_id"]
    return store.merge_entities(gone, keep_id)


def remember_split(a_id: str, b_id: str) -> None:
    """After a merge is undone, the two are not to be flagged again."""
    a, b = sorted((a_id, b_id))
    kind = db.one("SELECT kind FROM crm_entities WHERE id = ?", (a,))
    if kind is None:
        return
    now = db.now()
    db.execute("INSERT INTO crm_duplicates (id, a_id, b_id, kind, score, reasons, status, created_at, updated_at) "
               "VALUES (?, ?, ?, ?, 0, '[]', 'not_same', ?, ?) ON CONFLICT(a_id, b_id) DO UPDATE SET status = 'not_same', updated_at = excluded.updated_at",
               (db.new_id(), a, b, kind["kind"], now, now))
