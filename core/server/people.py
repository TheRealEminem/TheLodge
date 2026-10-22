"""The people directory: one way to find a person, whichever module or family app knows them (the blueprint's §6).

Each module that knows people gives its part through Module.people, (q, limit) -> [{id, name, email?, detail?,
is_self?}], and the host merges them, like search.py does. People in other family apps on this Mac come from their
"people.search" offer (family.call); when none of them is open, the local answers still come back, with a sentence
saying how to see the rest.

You always come back as "core:me", never as a module's own record of you, so you are stored the same way in every
module and every app. Someone known to two places by the same email shows once, as the first place's ref.
"""
import logging

from . import family, module, settings

log = logging.getLogger("core.people")

OFFER = "people.search"
ME = "core:me"
FAMILY_TIMEOUT = 2.0        # seconds: a picker is waiting on this


def me() -> dict:
    name = (settings.section("core").get("your_name") or "").strip()
    return {"ref": ME, "name": name or "You", "email": None, "detail": "You", "module": "core"}


def find(q: str, limit: int = 8) -> dict:
    """{"people": [{ref, name, email, detail, module}], "note": str | None}, best first: you (when you match, or q
    is empty), then names that start with q, then names with a word that does, then the rest. "note" says how to see
    people another family app knows when that app is closed."""
    q = (q or "").strip()
    limit = max(1, min(int(limit or 8), 50))
    found: list[dict] = []
    for m in module.all_modules():
        if not m.people:
            continue
        try:
            for p in m.people(q, limit) or []:
                ref = ME if p.get("is_self") else f"{m.id}:{p['id']}"
                found.append({"ref": ref, "name": p.get("name") or "", "email": p.get("email") or None,
                              "detail": p.get("detail") or None, "module": m.id})
        except Exception:  # noqa: BLE001 - one module's broken directory shouldn't hide the others
            log.exception("The people directory failed in %s", m.id)

    note = None
    if q and _family_offers():
        try:
            for p in family.call(OFFER, timeout=FAMILY_TIMEOUT, q=q, limit=limit) or []:
                if isinstance(p, dict) and p.get("ref") and p.get("name"):
                    found.append({"ref": p["ref"], "name": p["name"], "email": p.get("email") or None,
                                  "detail": p.get("detail") or None, "module": "family"})
        except family.Unavailable as e:
            note = str(e)
        except Exception:  # noqa: BLE001 - another app's odd answer mustn't break this one's picker
            log.exception("people.search from the family failed")

    return {"people": _merge(q, found)[:limit], "note": note}


def by_email(email: str) -> str | None:
    """The one ref with this email, or None (nobody, or more than one person)."""
    email = (email or "").strip().lower()
    if not email:
        return None
    refs = {p["ref"] for p in find(email, 50)["people"] if (p["email"] or "").lower() == email}
    return refs.pop() if len(refs) == 1 else None


def _family_offers() -> bool:
    """Whether asking the family could find anyone: a module here offers it, or another installed family app does."""
    if family.local_handler(OFFER):
        return True
    try:
        return any(OFFER in a["offers"] and not a["self"] for a in family.apps())
    except Exception:  # noqa: BLE001 - an unreadable family file just means no family people
        log.exception("couldn't read the family's apps")
        return False


def _rank(q: str, name: str) -> int:
    n, ql = name.lower(), q.lower()
    if not ql:
        return 0
    if n.startswith(ql):
        return 0
    if any(word.startswith(ql) for word in n.split()):
        return 1
    if ql in n:
        return 2
    return 3


def _merge(q: str, found: list[dict]) -> list[dict]:
    """One row per person: refs merged, the same email merged (the first place to know them wins), you first."""
    you = me()
    out: list[dict] = []
    seen_refs: set[str] = set()
    seen_emails: dict[str, dict] = {}
    for p in found:
        if p["ref"] == ME:
            you["email"] = you["email"] or p["email"]
            continue
        email = (p["email"] or "").lower()
        if p["ref"] in seen_refs or (email and email in seen_emails):
            continue
        seen_refs.add(p["ref"])
        if email:
            seen_emails[email] = p
        out.append(p)
    out.sort(key=lambda p: (_rank(q, p["name"]), p["name"].lower()))   # stable: each source's order within a rank
    ql = q.lower()
    you_match = (not ql or any(p["ref"] == ME for p in found) or ql in you["name"].lower()
                 or "you".startswith(ql) or "me" == ql)
    if you["email"] and you["email"].lower() in seen_emails:          # you, known elsewhere by your email
        out = [p for p in out if (p["email"] or "").lower() != you["email"].lower()]
    return ([you] if you_match else []) + out
