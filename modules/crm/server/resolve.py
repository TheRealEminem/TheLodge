"""Entity resolution: find existing records an incoming name probably refers to.

Postgres did the fuzzy part with pg_trgm. Here the names (and aliases) of each kind are held in memory and
scored with the same idea: trigram similarity, plus a "word" variant that lets a short name match inside a
longer one ("Kellan Trust" in "Kellan Trust USA"). The index is rebuilt whenever the CRM's tables change.
"""
import re
from dataclasses import dataclass

from . import store
from .model import Entity

_PRIORITY = {"email": 0, "exact name": 1, "alias": 2, "similar name": 3}
_STRONG = ("email", "exact name", "alias")
SIMILAR_MIN = 0.35

# Words that say what kind of organization something is, not which one.
# "Oak Foundation" vs "Gates Foundation" share only these, so they aren't a match.
_GENERIC_ORG_WORDS = {
    "the", "of", "and", "for", "a", "an", "&", "inc", "llc", "ltd", "co", "corp", "corporation", "company",
    "foundation", "trust", "fund", "capital", "ventures", "partners", "group", "consulting", "consultants",
    "associates", "holdings", "network", "association", "society", "institute", "center", "centre", "hub",
    "innovation", "innovations", "labs", "lab", "solutions", "systems", "technologies", "technology", "tech",
    "services", "international", "global", "health", "university", "college", "school", "program", "usa", "us",
}


def _distinctive(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in _GENERIC_ORG_WORDS}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _trigrams(words: list[str]) -> set[str]:
    out: set[str] = set()
    for w in words:
        padded = f"  {w} "
        out.update(padded[i:i + 3] for i in range(len(padded) - 2))
    return out


def similarity(a: str, b: str) -> float:
    ta, tb = _trigrams(_words(a)), _trigrams(_words(b))
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _sequence(words: list[str]) -> list[str]:
    """Trigrams in text order (repeats kept), each word padded the way pg_trgm does."""
    seq: list[str] = []
    for w in words:
        padded = f"  {w} "
        seq.extend(padded[i:i + 3] for i in range(len(padded) - 2))
    return seq


def word_similarity(needle: str, haystack: str) -> float:
    """pg_trgm's word_similarity: the best Jaccard between the needle's trigrams and any run of consecutive
    trigrams in the haystack. A short name scores high when it sits inside a longer one ("Kellan Trust" in
    "Kellan Trust USA"), and a typo'd name scores high against the word it was meant to be."""
    a = _trigrams(_words(needle))
    seq = _sequence(_words(haystack))
    hits = [i for i, t in enumerate(seq) if t in a]
    if not a or not hits:
        return 0.0
    best = 0.0
    for lo_i, lo in enumerate(hits):
        window: set[str] = set()
        pos = lo
        for hi in hits[lo_i:]:
            window.update(seq[pos:hi + 1])
            pos = hi + 1
            common = len(a & window)
            best = max(best, common / (len(a) + len(window) - common))
    return best


# ── Could these two names be the same one? ────────────────────────────
#
# Similar letters say which records are worth showing you, not that two names are the same. These are the rules for
# linking without asking: "Serena Holt" is not "John Holt", "Cascade Wild" is not "Summit Cascade", and "Dana"
# alone could be any Dana.

def _word_like(a: str, b: str) -> bool:
    """The same word, a slip of the pen, or one long word's variant ("Entrepreneurs", "Entrepreneurship")."""
    from .duplicates import _slip
    return a == b or _slip(a, b) or (min(len(a), len(b)) >= 7 and a[:7] == b[:7])


def name_fit(kind: str, written: str, record: str) -> str:
    """"same": the same name, spelled alike. "partial": a first name or a surname alone beside a full name, which
    only something else (a shared hat) can settle. "different": another name that happens to look similar."""
    from .duplicates import _first_names_match, name_words, org_words
    if kind == "person":
        a, b = name_words(written), name_words(record)
        if not a or not b:
            return "different"
        if a == b:
            return "same"
        if len(a) == 1 or len(b) == 1:
            short, full = (a, b) if len(a) == 1 else (b, a)
            return "partial" if _first_names_match(short[0], full[0]) or short[0] == full[-1] else "different"
        same_first = _first_names_match(a[0], b[0]) or _word_like(a[0], b[0])
        return "same" if same_first and _word_like(a[-1], b[-1]) else "different"
    a = [w for w in org_words(written) if w not in _GENERIC_ORG_WORDS]
    b = [w for w in org_words(record) if w not in _GENERIC_ORG_WORDS]
    if not a or not b:
        return "different"   # only generic words ("Lab", "Group"): nothing says which one
    short, long_ = sorted((a, b), key=len)
    return "same" if all(any(_word_like(w, x) for x in long_) for w in short) else "different"


def as_written(name: str, text: str) -> str:
    """A person's name as the source gives it. Told who's already in the book, a model turns "Dana" into the "Dana
    Whitfield" it was shown: when the surname appears nowhere in the source, only the first name was written."""
    from .duplicates import _plain, name_words
    words = name_words(name)
    if len(words) < 2:
        return name
    found = set(re.findall(r"[a-z0-9]+", _plain(text)))
    if words[-1] in found or words[0] not in found:
        return name
    return name.split()[0]


@dataclass
class Candidate:
    entity: Entity
    score: float
    reason: str
    written: str = ""    # the name as it was written, which this record might be

    @property
    def fit(self) -> str:
        return name_fit(self.entity.kind, self.written, self.entity.name) if self.reason == "similar name" else "same"

    def as_dict(self, subtitle: str | None = None) -> dict:
        return {"id": self.entity.id, "name": self.entity.name, "kind": self.entity.kind,
                "subtitle": subtitle, "score": round(self.score, 3), "reason": self.reason}


class _Index:
    version = -1
    by_kind: dict[str, list[Entity]] = {}


_index = _Index()


def _entities(kind: str) -> list[Entity]:
    if _index.version != store.version():
        _index.version = store.version()
        _index.by_kind = {}
        for e in store.all_entities():
            _index.by_kind.setdefault(e.kind, []).append(e)
    return _index.by_kind.get(kind, [])


def find_candidates(kind: str, name: str, email: str | None = None, limit: int = 3,
                    extra: list[Entity] | None = None, blocked: set[str] | None = None) -> list[Candidate]:
    """`extra`: records not in the index yet (an import in progress that hasn't committed): considered as well."""
    found: dict[str, Candidate] = {}
    # Records you've said this name isn't.
    blocked = store.blocked_for(name) if blocked is None else blocked

    def add(entity: Entity, score: float, reason: str) -> None:
        if entity.id in blocked:
            return
        if entity.id not in found or found[entity.id].score < score:
            found[entity.id] = Candidate(entity, score, reason, name)

    entities = _entities(kind)
    if extra:
        known = {e.id for e in entities}
        entities = [*entities, *(e for e in extra if e.kind == kind and e.id not in known)]
    if email:
        wanted = email.strip().lower()
        for e in entities:
            if str(e.attributes.get("email") or "").lower() == wanted:
                add(e, 1.0, "email")

    needle = name.strip().lower()
    if not needle:
        return list(found.values())

    for e in entities:
        if any(str(a).lower() == needle for a in e.attributes.get("aliases") or []):
            add(e, 0.97, "alias")

    scored = []
    for e in entities:
        lowered = e.name.lower()
        s = max(similarity(needle, lowered), word_similarity(needle, lowered), word_similarity(lowered, needle))
        if s >= SIMILAR_MIN:
            scored.append((s, e))
    scored.sort(key=lambda t: -t[0])
    needle_words = _distinctive(needle)
    for s, e in scored[: limit + 2]:
        exact = e.name.strip().lower() == needle
        if not exact and kind == "organization" and needle_words and not needle_words & _distinctive(e.name):
            continue  # only generic words in common ("... Foundation", "... Consulting")
        add(e, 1.0 if exact else s, "exact name" if exact else "similar name")

    return sorted(found.values(), key=lambda c: (-c.score, _PRIORITY[c.reason]))[:limit]


def pick_match(candidates: list[Candidate], threshold: float) -> tuple[Candidate | None, bool]:
    """Best candidate to link without asking, and whether it needs you to choose. A strong match (email, exact name,
    alias) links; a similar name links only if name_fit says it's the same name. A first name alone beside a full name
    asks; a name that only looks similar makes a new record (with the lookalikes shown when you review it)."""
    usable = [c for c in candidates if c.score >= threshold and c.fit != "different"]
    if not usable:
        return None, False
    top = usable[0]
    runner_up = usable[1] if len(usable) > 1 else None
    if top.reason in _STRONG and not (runner_up and runner_up.reason in _STRONG):
        return top, False
    if top.fit == "partial":
        return None, True
    if runner_up and runner_up.score >= top.score - 0.05:
        return None, True
    return top, False
