def make(client, kind, name, **extra):
    r = client.post("/api/crm/entities", json={"kind": kind, "name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def link(client, source, kind, target, **extra):
    r = client.post("/api/crm/relationships", json={"source_id": source["id"], "target_id": target["id"], "kind": kind, **extra})
    assert r.status_code == 201, r.text
    return r.json()
