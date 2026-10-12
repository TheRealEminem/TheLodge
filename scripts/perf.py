#!/usr/bin/env python
"""How does The Lodge cope with a book far bigger than anyone's? Builds a scratch database of synthetic people,
organizations, meetings, documents and topics (default 50,000 records and 250,000 lines) and times the calls the
app makes. Nothing real is touched: it works in a temporary folder.

    .venv/bin/python scripts/perf.py [--entities 50000] [--edges 250000]
"""
import argparse
import json
import os
import random
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument("--entities", type=int, default=50_000)
parser.add_argument("--edges", type=int, default=250_000)
parser.add_argument("--profile", action="store_true", help="show where the time goes for the first people list after a write")
args = parser.parse_args()
os.environ["LODGE_DATA_DIR"] = tempfile.mkdtemp(prefix="lodge-perf-")

from fastapi.testclient import TestClient  # noqa: E402

from core.server import app as app_module, db  # noqa: E402

app = app_module.create_app()
client = TestClient(app)
rnd = random.Random(7)
now = datetime.now(timezone.utc)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000Z")  # noqa: E731
hexid = lambda: uuid.uuid4().hex  # noqa: E731

n = args.entities
mix = {"person": int(n * .30), "organization": int(n * .10), "meeting": int(n * .40), "document": int(n * .15), "topic": int(n * .05)}
ids: dict[str, list[str]] = {k: [] for k in mix}
rows = []
for kind, count in mix.items():
    for i in range(count):
        e = hexid()
        ids[kind].append(e)
        name = f"{kind.title()} {i} {rnd.choice(['Nair', 'King', 'Lime', 'Okafor', 'Reyes', 'Albright'])}"
        when = iso(now - timedelta(days=rnd.randint(0, 700))) if kind in ("meeting", "document") else None
        attrs = {"email": f"p{i}@x{i % 900}.example", "title": "Director"} if kind == "person" else {}
        tags = rnd.sample(["investor", "mentor", "customer", "hardware", "advisor", "founder", "vc", "oregon"], rnd.randint(0, 3)) if kind == "person" else []
        rows.append((e, kind, name, "A summary." if rnd.random() < .5 else None, json.dumps(attrs), json.dumps(tags), when, 0, "demo", iso(now), iso(now)))
me = ids["person"][0]
with db.connect() as c:
    t = time.perf_counter()
    c.executemany("INSERT INTO crm_entities (id, kind, name, summary, attributes, tags, occurred_at, is_self, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    c.execute("UPDATE crm_entities SET is_self = 1 WHERE id = ?", (me,))
    seen: set[tuple] = set()
    edges = []

    def add(s, t_, kind, strength=3):
        if s != t_ and (s, t_, kind) not in seen:
            seen.add((s, t_, kind))
            edges.append((hexid(), s, t_, kind, "{}", strength, None, None, "demo", None, iso(now), iso(now)))

    for p in ids["person"]:
        add(p, rnd.choice(ids["organization"]), "works_at")
    for m in ids["meeting"]:
        add(me, m, "attended") if rnd.random() < .5 else None
        for p in rnd.sample(ids["person"], rnd.randint(1, 5)):
            add(p, m, "attended")
        for p in rnd.sample(ids["person"], rnd.randint(0, 2)):
            add(p, m, "discussed_in")
        if rnd.random() < .3:
            add(rnd.choice(ids["topic"]), m, "discussed_in")
    for d in ids["document"]:
        for p in rnd.sample(ids["person"], rnd.randint(0, 3)):
            add(p, d, "mentioned_in")
    for p in rnd.sample(ids["person"], min(400, len(ids["person"]))):
        add(me, p, "knows", rnd.randint(1, 5))
    while len(edges) < args.edges:
        a, b = rnd.sample(ids["person"], 2)
        add(a, b, rnd.choice(["knows", "introduced_by", "related_to"]))
    c.executemany("INSERT INTO crm_relationships (id, source_id, target_id, kind, properties, strength, started_at, ended_at, source, evidence_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", edges)
    c.execute("INSERT INTO crm_notes (id, entity_id, body, occurred_at, source, created_at) SELECT lower(hex(randomblob(16))), id, 'A note', created_at, 'manual', created_at FROM crm_entities WHERE kind = 'person' LIMIT 20000")
print(f"built {len(rows):,} records, {len(edges):,} lines in {time.perf_counter() - t:.1f}s (database {Path(db.DB_PATH).stat().st_size / 1e6:.0f} MB)\n")

from modules.crm.server import research, snapshot, store, views  # noqa: E402


def timed(label, fn):
    t0 = time.perf_counter()
    out = fn()
    print(f"  {label:<44}{(time.perf_counter() - t0) * 1000:>9.0f} ms")
    return out


store._touch()
print("first call after a change (builds what's cached):")
timed("load the whole graph", snapshot.load)
timed("work out every connection (tiers)", views.get)
timed("people list, 100 rows", lambda: client.get("/api/crm/people?limit=100").json())
print("\nthen, with the cache warm:")
timed("people list, 100 rows", lambda: client.get("/api/crm/people?limit=100").json())
timed("people, strong only", lambda: client.get("/api/crm/people?tier=strong").json())
timed("people, search 'Okafor'", lambda: client.get("/api/crm/people?q=Okafor").json())
timed("Home (dashboard)", lambda: client.get("/api/crm/dashboard").json())
timed("research flags", lambda: client.get("/api/crm/research").json())
timed("organizations", lambda: client.get("/api/crm/organizations?limit=50").json())
timed("a person's page (detail + context)", lambda: (client.get(f"/api/crm/entities/{ids['person'][5]}").json(), client.get(f"/api/crm/entities/{ids['person'][5]}/context").json()))
timed("search 'Reyes'", lambda: client.get("/api/search?q=Reyes").json())
timed("network", lambda: client.get("/api/crm/network").json())
timed("network groups list", lambda: client.get("/api/crm/network/tags").json())
net = client.get("/api/crm/network").json()
print(f"    (network sent {len(net.get('nodes', []))} people and {len(net.get('links', []))} lines, {len(json.dumps(net)) / 1e6:.1f} MB)")
timed("graph overview", lambda: client.get("/api/crm/graph").json())
print("\nwrites:")
timed("add a person (cache rebuilt on next read)", lambda: client.post("/api/crm/entities", json={"kind": "person", "name": "New Person"}).json())
timed("people list right after that write", lambda: client.get("/api/crm/people?limit=100").json())
from core.server import backup  # noqa: E402
timed("backup", backup.make)
timed("export everything to JSON", backup.export_all)

if args.profile:
    import cProfile
    import pstats
    store._touch()
    prof = cProfile.Profile()
    prof.enable()
    from modules.crm.server import routes_people
    routes_people.list_people(tier=None, org=None, tag=None, q=None, needs_research=False, sort="strength", limit=100, offset=0)
    prof.disable()
    print("\nwhere the time goes (people list after a write):")
    pstats.Stats(prof).sort_stats("cumulative").print_stats(18)
