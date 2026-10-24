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


@dataclass
class Candidate:
    entity: Entity
    score: float
    reason: str

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
                    extra: list[Entity] | None = None) -> list[Candidate]:
    """`extra`: records not in the index yet (an import in progress that hasn't committed): considered as well."""
    found: dict[str, Candidate] = {}

    def add(entity: Entity, score: float, reason: str) -> None:
        if entity.id not in found or found[entity.id].score < score:
            found[entity.id] = Candidate(entity, score, reason)

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
    """Best candidate to auto-link, and whether the choice was ambiguous."""
    if not candidates or candidates[0].score < threshold:
        return None, False
    top = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None
    if top.reason in _STRONG and not (runner_up and runner_up.reason in _STRONG):
        return top, False
    if runner_up and runner_up.score >= top.score - 0.05:
        return None, True
    return top, False
