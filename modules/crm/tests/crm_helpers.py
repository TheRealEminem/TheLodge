from core.server import jobs
from modules.crm.server.extraction import ExtractedEntity, Extraction

NOTES = """Helio pilot sync
Attendees: Priya Nair (Helio Cold Chain), Tom Albright <tom@frostline.example>, Me

Priya shared pilot results. Frostline Logistics wants to expand to 50 trucks.
- [ ] Tom to send the fleet list
Action: Me to draft the SOW
"""


def make(client, kind, name, **extra):
    r = client.post("/api/crm/entities", json={"kind": kind, "name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def link(client, source, kind, target, **extra):
    r = client.post("/api/crm/relationships", json={"source_id": source["id"], "target_id": target["id"], "kind": kind, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def post_notes(client, text=NOTES, **extra):
    r = client.post("/api/crm/ingest/notes", json={"text": text, **extra})
    assert r.status_code == 202, r.text
    jobs.drain()
    return client.get(f"/api/crm/ingest/jobs/{r.json()['id']}").json()


def upload(client, *files, auto_apply=True):
    r = client.post("/api/crm/ingest/files", files=[("files", (n, d, "text/plain")) for n, d in files],
                    data={"auto_apply": "true" if auto_apply else "false"})
    assert r.status_code == 202, r.text
    jobs.drain()
    return {j["filename"]: client.get(f"/api/crm/ingest/jobs/{j['id']}").json() for j in r.json()}


def entity(ref, name, kind="person", role="mentioned", **extra):
    return ExtractedEntity(ref=ref, kind=kind, name=name, role=role, **extra)


def extraction(entities, **extra):
    base = dict(doc_type="meeting_notes", title="Pilot call", summary="They talked about the pilot.", entities=entities)
    return Extraction(**{**base, **extra})
