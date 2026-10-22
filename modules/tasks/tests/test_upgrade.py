"""Step 2 on a database that only had step 1 (The Lodge's to-dos today): every to-do becomes a work item, nothing
is lost, and the old columns still read the same."""
import sqlite3

from modules.tasks.server import store


def v1_database(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(f"BEGIN; {store.MIGRATIONS[0]}; COMMIT;")
    conn.executemany(
        "INSERT INTO tasks_items (id, text, done, source_ref, created_at) VALUES (?, ?, ?, ?, ?)",
        [("a1", "Send the outline", 0, "notes:n1", "2026-10-01T09:00:00Z"),
         ("a2", "Book the venue", 1, None, "2026-10-02T10:00:00Z"),
         ("a3", "Call Ana", 1, "crm:m7", "2026-10-03T11:00:00Z")])
    conn.commit()
    return conn


def test_old_to_dos_become_work_items(tmp_path):
    conn = v1_database(tmp_path / "old.db")
    conn.executescript(f"BEGIN; {store.MIGRATIONS[1]}; COMMIT;")         # the way the host runs a step
    conn.row_factory = sqlite3.Row
    rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM tasks_items")}
    assert (rows["a1"]["status"], rows["a1"]["completed_at"], rows["a1"]["source"]) == ("todo", None, "action-item")
    assert (rows["a2"]["status"], rows["a2"]["completed_at"], rows["a2"]["source"]) == ("done", "2026-10-02T10:00:00Z", "manual")
    assert rows["a3"]["status"] == "done" and rows["a3"]["source"] == "action-item"
    for r in rows.values():
        assert r["updated_at"] == r["created_at"] and r["priority"] == 0 and r["notes"] == ""
        assert r["project_id"] is None and r["tags"] == "[]" and r["attributes"] == "{}"
    # what code written for step 1 reads is unchanged
    old = [tuple(r) for r in conn.execute("SELECT id, text, done, source_ref FROM tasks_items ORDER BY id")]
    assert old == [("a1", "Send the outline", 0, "notes:n1"), ("a2", "Book the venue", 1, None), ("a3", "Call Ana", 1, "crm:m7")]
    found = [r["id"] for r in conn.execute("SELECT id FROM tasks_fts WHERE tasks_fts MATCH 'venue'")]
    assert found == ["a2"]


def test_the_new_tables_keep_their_promises(tmp_path):
    conn = v1_database(tmp_path / "old.db")
    conn.executescript(f"BEGIN; {store.MIGRATIONS[1]}; COMMIT;")
    conn.execute("INSERT INTO tasks_projects (id, name, created_at, updated_at) VALUES ('p1', 'Relaunch', 'x', 'x')")
    conn.execute("INSERT INTO tasks_milestones (id, project_id, name, created_at, updated_at) VALUES ('m1', 'p1', 'Designs', 'x', 'x')")
    conn.execute("UPDATE tasks_items SET project_id = 'p1', milestone_id = 'm1' WHERE id = 'a1'")
    conn.execute("INSERT INTO tasks_items (id, text, created_at, parent_id) VALUES ('s1', 'A subtask', 'x', 'a1')")
    conn.execute("INSERT INTO tasks_blockers (item_id, blocked_by, created_at) VALUES ('a2', 'a1', 'x')")
    conn.execute("INSERT INTO tasks_updates (id, project_id, body, created_at) VALUES ('u1', 'p1', 'Going well', 'x')")
    for bad in ("INSERT INTO tasks_blockers (item_id, blocked_by, created_at) VALUES ('a1', 'a1', 'x')",
                "INSERT INTO tasks_updates (id, project_id, item_id, body, created_at) VALUES ('u2', 'p1', 'a1', 'b', 'x')",
                "INSERT INTO tasks_milestones (id, project_id, name, created_at, updated_at) VALUES ('m2', 'nope', 'n', 'x', 'x')"):
        try:
            conn.execute(bad)
            raise AssertionError(f"accepted: {bad}")
        except sqlite3.IntegrityError:
            pass
    conn.execute("DELETE FROM tasks_projects WHERE id = 'p1'")
    assert tuple(conn.execute("SELECT project_id, milestone_id FROM tasks_items WHERE id = 'a1'").fetchone()) == (None, None)
    assert conn.execute("SELECT count(*) FROM tasks_updates").fetchone()[0] == 0           # updates go with it
    conn.execute("DELETE FROM tasks_items WHERE id = 'a1'")
    assert conn.execute("SELECT count(*) FROM tasks_items WHERE id = 's1'").fetchone()[0] == 0   # subtasks too
    assert conn.execute("SELECT count(*) FROM tasks_blockers").fetchone()[0] == 0
