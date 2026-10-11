def test_items_can_be_made_found_and_deleted(client):
    item_id = client.post("/api/__id__", json={"title": "First __Name__ item"}).json()["id"]
    assert [i["id"] for i in client.get("/api/__id__").json()].count(item_id) == 1
    groups = client.get("/api/search", params={"q": "First __Name__"}).json()
    assert any(h["id"] == item_id for g in groups if g["module"] == "__id__" for h in g["hits"])
    assert client.delete(f"/api/__id__/{item_id}").status_code == 204
    assert client.get(f"/api/__id__/{item_id}").status_code == 404
