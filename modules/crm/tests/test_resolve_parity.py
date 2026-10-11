"""The new matcher against the old Postgres one: for each recorded query, same pick and same ambiguity.
The fixture is real names from the owner's data, so it isn't committed (.gitignore); the test skips without it."""
import json
from pathlib import Path

import pytest

from modules.crm.server import resolve, store

FIXTURE = Path(__file__).parent / "fixtures" / "real_names.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="real_names.json not recorded")


def mismatches():
    data = json.loads(FIXTURE.read_text())
    for e in data["entities"]:
        attrs = {"aliases": e["aliases"]} if e["aliases"] else {}
        if e["email"]:
            attrs["email"] = e["email"]
        store.create_entity(e["kind"], e["name"], attributes=attrs)
    bad = []
    for q in data["queries"]:
        cands = resolve.find_candidates(q["kind"], q["name"])
        match, amb = resolve.pick_match(cands, 0.6)
        got = (match.entity.name if match else None, amb)
        if got != (q["pick"], q["ambiguous"]):
            bad.append((q["kind"], q["name"], (q["pick"], q["ambiguous"]), got,
                        [(c["name"], c["reason"], c["score"]) for c in q["cands"]],
                        [(c.entity.name, c.reason, round(c.score, 2)) for c in cands]))
    return data, bad


def test_same_verdicts_as_postgres(client):
    data, bad = mismatches()
    for b in bad[:40]:
        print(b)
    assert not bad, f"{len(bad)} of {len(data['queries'])} differ"
