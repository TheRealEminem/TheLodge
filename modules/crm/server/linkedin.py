"""Import LinkedIn's official data export (Settings -> Data privacy -> Get a copy of your data -> Connections).
No scraping involved. Connections.csv starts with a few "Notes:" lines, then:

    First Name,Last Name,URL,Email Address,Company,Position,Connected On

Importing the same file again changes nothing: people are found by profile URL or a unique name, and lines that
already exist are not added twice.
"""
import csv
import io
from datetime import date, datetime

from core.server import db

from . import inbox, store

HEADER_PREFIX = "first name"


class LinkedInFormatError(ValueError):
    pass


def parse_connections_csv(content: str) -> list[dict]:
    lines = content.lstrip("﻿").splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip().lower().startswith(HEADER_PREFIX)), None)
    if start is None:
        raise LinkedInFormatError(
            "Couldn't find the 'First Name,Last Name,URL,...' header. Upload Connections.csv from LinkedIn's data export.")
    rows = []
    for raw in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        name = f"{row.get('first name', '')} {row.get('last name', '')}".strip()
        if not name:
            continue
        rows.append({"name": name, "url": row.get("url") or None, "email": row.get("email address") or None,
                     "company": row.get("company") or None, "position": row.get("position") or None,
                     "connected_on": _parse_date(row.get("connected on"))})
    return rows


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _norm_url(url: str | None) -> str | None:
    return url.rstrip("/").lower() if url else None


def import_connections(rows: list[dict], filename: str | None = None) -> dict:
    """Adds the connections and returns the inbox row recording what was done."""
    counts = {"rows": len(rows), "people_created": 0, "people_updated": 0, "orgs_created": 0, "relationships": 0}
    with inbox.write_lock, db.connect() as c:
        me = next((e for e in store.all_entities("person", c) if e.is_self), None)
        people = store.all_entities("person", c)
        by_url = {_norm_url(p.attributes.get("linkedin_url")): p for p in people if p.attributes.get("linkedin_url")}
        name_counts: dict[str, int] = {}
        for p in people:
            name_counts[p.name.lower()] = name_counts.get(p.name.lower(), 0) + 1
        by_name = {p.name.lower(): p for p in people if name_counts[p.name.lower()] == 1}
        org_by_name = {o.name.lower(): o for o in store.all_entities("organization", c)}

        existing: set[tuple[str, str, str]] = set()
        for r in c.execute("SELECT source_id, target_id, kind FROM crm_relationships WHERE kind IN ('works_at', 'knows')"):
            existing.add((r["source_id"], r["target_id"], r["kind"]))
            if r["kind"] == "knows":
                existing.add((r["target_id"], r["source_id"], r["kind"]))

        def add_edge(s: str, t: str, kind: str, **fields) -> None:
            if (s, t, kind) in existing or s == t:
                return
            store.create_edge(s, t, kind, conn=c, source="linkedin", **fields)
            existing.add((s, t, kind))
            if kind == "knows":
                existing.add((t, s, kind))
            counts["relationships"] += 1

        for row in rows:
            person = by_url.get(_norm_url(row["url"])) or by_name.get(row["name"].lower())
            wanted = {k: v for k, v in (("linkedin_url", row["url"]), ("email", row["email"]), ("title", row["position"])) if v}
            if person is None:
                person = store.create_entity("person", row["name"], attributes=wanted, source="linkedin", conn=c)
                by_name[row["name"].lower()] = person
                if row["url"]:
                    by_url[_norm_url(row["url"])] = person
                counts["people_created"] += 1
            else:
                attrs = dict(person.attributes or {})
                filled = {k: v for k, v in wanted.items() if not attrs.get(k)}
                if filled:
                    person = store.update_entity(person.id, conn=c, attributes={**attrs, **filled})
                    counts["people_updated"] += 1

            if row["company"]:
                org = org_by_name.get(row["company"].lower())
                if org is None:
                    org = store.create_entity("organization", row["company"], source="linkedin", conn=c)
                    org_by_name[row["company"].lower()] = org
                    counts["orgs_created"] += 1
                add_edge(person.id, org.id, "works_at", properties={"title": row["position"]} if row["position"] else {})
            if me is not None:
                add_edge(me.id, person.id, "knows", strength=2, started_at=row["connected_on"],
                         properties={"context": "LinkedIn connection"})
    store._touch()
    item = inbox.create("linkedin_csv", title=f"LinkedIn import{f' ({filename})' if filename else ''}", status="applied")
    inbox.update(item["id"], extractor="linkedin", result=counts)
    return inbox.require(item["id"])
