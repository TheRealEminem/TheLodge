"""__Name__'s tables (__id___*) and the queries on them. Only this module touches these tables."""
from core.server import db

MIGRATIONS = [
    """
    CREATE TABLE __id___items (
        id          TEXT PRIMARY KEY,
        title       TEXT NOT NULL,
        created_at  TEXT NOT NULL
    );
    """,
]


def create(title: str) -> str:
    item_id = db.new_id()
    db.execute("INSERT INTO __id___items (id, title, created_at) VALUES (?, ?, ?)", (item_id, title, db.now()))
    return item_id


def all_items() -> list[dict]:
    return db.query("SELECT * FROM __id___items ORDER BY created_at DESC")


def get(item_id: str) -> dict | None:
    return db.one("SELECT * FROM __id___items WHERE id = ?", (item_id,))


def delete(item_id: str) -> None:
    db.execute("DELETE FROM __id___items WHERE id = ?", (item_id,))


def describe(item_id: str) -> dict | None:
    row = get(item_id)
    return {"title": row["title"], "href": f"#/__id__/{item_id}"} if row else None


def search(q: str, limit: int) -> list[dict]:
    rows = db.query("SELECT id, title FROM __id___items WHERE title LIKE ? ORDER BY created_at DESC LIMIT ?", (f"%{q}%", limit))
    return [{"id": r["id"], "title": r["title"], "snippet": ""} for r in rows]
