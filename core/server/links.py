"""Links between things in different modules ("this task came from that note").

Things are named by refs, "<module>:<id>". The host stores the pairs; each module says what its own refs
are called (Module.describe), so a module can show what's linked to it without knowing who links.
"""
from . import db, events, module


def ref(module_id: str, item_id: str) -> str:
    return f"{module_id}:{item_id}"


def add(from_ref: str, to_ref: str, kind: str = "related") -> None:
    db.execute("INSERT OR IGNORE INTO core_links (from_ref, to_ref, kind, created_at) VALUES (?, ?, ?, ?)",
               (from_ref, to_ref, kind, db.now()))
    events.publish("core.links.changed", {"refs": [from_ref, to_ref]})


def remove(from_ref: str, to_ref: str, kind: str | None = None) -> None:
    if kind:
        db.execute("DELETE FROM core_links WHERE from_ref = ? AND to_ref = ? AND kind = ?", (from_ref, to_ref, kind))
    else:
        db.execute("DELETE FROM core_links WHERE from_ref = ? AND to_ref = ?", (from_ref, to_ref))
    events.publish("core.links.changed", {"refs": [from_ref, to_ref]})


def forget(ref_: str) -> None:
    """Drops every link to or from something that no longer exists."""
    db.execute("DELETE FROM core_links WHERE from_ref = ? OR to_ref = ?", (ref_, ref_))


def linked(ref_: str) -> list[dict]:
    """Everything linked to ref_, either way round, described by its own module. Things whose module is
    turned off are left out (their links stay, and come back when it's on again)."""
    rows = db.query(
        "SELECT to_ref AS other, kind, 'to' AS direction, created_at FROM core_links WHERE from_ref = ? "
        "UNION ALL SELECT from_ref, kind, 'from', created_at FROM core_links WHERE to_ref = ? ORDER BY created_at",
        (ref_, ref_),
    )
    out = []
    for row in rows:
        found = module.describe(row["other"])
        if found:
            out.append({**found, "kind": row["kind"], "direction": row["direction"]})
    return out


def sources(target: str, kind: str | None = None) -> list[str]:
    """Refs that link *to* target (e.g. where a task came from)."""
    if kind:
        return [r["from_ref"] for r in db.query("SELECT from_ref FROM core_links WHERE to_ref = ? AND kind = ?", (target, kind))]
    return [r["from_ref"] for r in db.query("SELECT from_ref FROM core_links WHERE to_ref = ?", (target,))]
