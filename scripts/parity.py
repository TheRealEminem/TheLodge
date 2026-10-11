#!/usr/bin/env python
"""Compare the old DynaCRM API with The Lodge's, on the same data (after scripts/import-dynacrm.py).

    docker compose run -d --no-deps -p 8010:8000 --name old-api api      # in the old project folder
    .venv/bin/python scripts/parity.py [--old http://localhost:8010] [--data-dir ./data]

For every check it prints OK or the first differences. Ids are compared in their hex form, and timestamps to
the second. Exit code 0 means no differences. Development only (needs `httpx`, already a dependency).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
STAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|\+00:00)$")


# Lists the old app built in an arbitrary order among ties; compared as sets.
UNORDERED = {"via", "mutual", "relationships", "nodes", "links"}
# People with several current jobs: the old app named a different employer in lists than on profiles (it
# was inconsistent); The Lodge uses the newest everywhere. Employer-derived fields are skipped for them.
MULTI: set[str] = set()


def norm(x):
    if isinstance(x, dict):
        x = dict(x)
        if "depth" in x and "degree" in x:
            x.pop("tier", None)  # graph nodes: new in The Lodge
        if x.get("kind") == "person" and str(x.get("id", "")).replace("-", "") in MULTI:
            x["subtitle"] = None
        if isinstance(x.get("person"), dict) and str(x["person"].get("id", "")).replace("-", "") in MULTI:
            x["org"] = None
        return {k: (sorted(norm(v), key=lambda e: e["id"]) if k in UNORDERED and isinstance(v, list) else norm(v))
                for k, v in x.items()}
    if isinstance(x, list):
        return [norm(v) for v in x]
    if isinstance(x, str):
        x = UUID.sub(lambda m: m.group(0).replace("-", "").lower(), x)
        m = STAMP.match(x)
        if m:
            return m.group(1) + "Z"
    return x


def diff(a, b, path="", out=None, limit=6):
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if type(a) is not type(b):
        out.append(f"{path}: {a!r} != {b!r}")
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}/{k}: missing in {'old' if k not in a else 'new'}")
            else:
                diff(a[k], b[k], f"{path}/{k}", out, limit)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: {len(a)} items != {len(b)} items")
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out, limit)
    elif a != b:
        out.append(f"{path}: {a!r} != {b!r}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="http://localhost:8010")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    args = ap.parse_args()
    os.environ["LODGE_DATA_DIR"] = args.data_dir
    os.environ["LODGE_UI_DIR"] = "/nonexistent"
    sys.path.insert(0, str(ROOT))
    import logging
    import httpx
    logging.disable(logging.INFO)
    from fastapi.testclient import TestClient

    from core.server.app import app

    from core.server import db
    MULTI.update(r["id"] for r in db.query(
        "SELECT source_id AS id FROM crm_relationships WHERE kind = 'works_at' AND ended_at IS NULL "
        "GROUP BY source_id HAVING count(*) > 1"))
    print(f"({len(MULTI)} people have several current employers; their employer fields are not compared)\n")
    old = httpx.Client(base_url=args.old + "/api", timeout=60)
    new = TestClient(app, base_url="http://lodge/api/crm")
    failures = 0

    def get(client, path, **params):
        r = client.get(path, params=params)
        r.raise_for_status()
        return norm(r.json())

    def check(label, a, b, ignore=()):
        nonlocal failures
        for k in ignore:
            a.pop(k, None), b.pop(k, None)
        problems = diff(a, b)
        print(f"{'OK  ' if not problems else 'FAIL'} {label}")
        for p in problems:
            print("       ", p)
        failures += bool(problems)

    # Whole-network views.
    od, nd = get(old, "/dashboard"), get(new, "/dashboard")
    check("dashboard (counts, tiers, every list, activity)", od, nd)

    op = get(old, "/people", limit=1000)
    np_ = get(new, "/people", limit=1000)
    check(f"people: {op['total']} rows, order, tier and evidence for each", op, np_)

    oo = get(old, "/organizations", scope="all", limit=1000)
    no = get(new, "/organizations", scope="all", limit=1000)
    check(f"organizations: {oo['total']} rows, scopes {oo['scopes']}", oo, no)

    for sort in ("name", "recent", "meetings"):
        check(f"people sorted by {sort}", get(old, "/people", limit=1000, sort=sort), get(new, "/people", limit=1000, sort=sort))
    for scope in ("known", "mentioned"):
        check(f"organizations scope {scope}", get(old, "/organizations", scope=scope, limit=1000),
              get(new, "/organizations", scope=scope, limit=1000))

    # Entity pages: the top people and organizations, every meeting and document.
    ids = [r["person"]["id"] for r in op["items"][:12]] + [r["org"]["id"] for r in oo["items"][:8]]
    for kind in ("meeting", "document", "topic"):
        page = get(old, "/entities", kind=kind, limit=500)
        ids += [e["id"] for e in page["items"][:6]]
    for eid in ids:
        name = get(old, f"/entities/{eid}")["entity"]["name"]
        check(f"context · {name}", get(old, f"/entities/{eid}/context"), get(new, f"/entities/{eid}/context"))
        check(f"detail · {name}", get(old, f"/entities/{eid}"), get(new, f"/entities/{eid}"))
        by_time = lambda t: sorted(t, key=lambda e: (e["at"], e["id"]))  # noqa: E731 - equal times: old order was arbitrary
        check(f"timeline · {name}", by_time(get(old, f"/entities/{eid}/timeline")), by_time(get(new, f"/entities/{eid}/timeline")))

    # How the owner reaches other people.
    for r in op["items"][::max(1, len(op["items"]) // 10)][:10]:
        t = r["person"]["id"]
        for through in (None, "person"):
            params = {"target": t, **({"through": through} if through else {})}
            check(f"paths to {r['person']['name']}{' (via people)' if through else ''}",
                  get(old, "/graph/paths", **params), get(new, "/graph/paths", **params))

    # Lists and graph overview.
    for kind in ("person", "organization", "meeting", "document", "topic"):
        for sort in ("name", "connections"):
            check(f"entities {kind} by {sort}", get(old, "/entities", kind=kind, sort=sort, limit=500),
                  get(new, "/entities", kind=kind, sort=sort, limit=500))
    check("graph overview (nodes, links)", get(old, "/graph"), get(new, "/graph"))

    print()
    print("No differences." if not failures else f"{failures} check(s) differ.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
