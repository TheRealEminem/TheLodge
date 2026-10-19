"""Likely duplicates and undoable merges, mounted under /api/crm. Nothing here merges on its own: every merge is
a request you made, and every merge can be undone."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.server import db, jobs, schedule

from . import duplicates, store

router = APIRouter()


class KeepIn(BaseModel):
    keep_id: str


def _brief(e) -> dict:
    return {"id": e.id, "name": e.name, "kind": e.kind}


def _guard(fn, *args):
    try:
        return fn(*args)
    except store.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except store.MergeError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/duplicates")
def list_duplicates(entity_id: str | None = None, limit: int = Query(100, ge=1, le=500)):
    """Pairs that look like one record twice, the surest first. With entity_id, only that record's."""
    return duplicates.listing(entity_id, limit)


@router.post("/duplicates/check", status_code=202)
def check_duplicates():
    """Look again now, rather than at the next regular check."""
    duplicates.forget_check()
    jobs.enqueue("crm", "duplicates_check", schedule.TARGET)
    return {"queued": True}


@router.post("/duplicates/{pair_id}/merge")
def merge_pair(pair_id: str, body: KeepIn):
    """Your OK: fold the other record of the pair into the one you keep. It can be undone from the kept record."""
    return _brief(_guard(duplicates.merge, pair_id, body.keep_id))


@router.post("/duplicates/{pair_id}/not-same")
def not_same(pair_id: str):
    _guard(duplicates.not_same, pair_id)
    return {"ok": True}


@router.get("/entities/{entity_id}/merges")
def merges(entity_id: str):
    """Records merged into this one that can still be split off again."""
    return store.merges_into(entity_id)


@router.get("/entities/{entity_id}/moved")
def moved(entity_id: str):
    """Where a record that was merged away lives now (an old link to it), or null."""
    return {"id": store.merged_into(entity_id)}


@router.post("/merges/{merge_id}/undo")
def undo_merge(merge_id: str):
    """Split a merged record off again, with its own meetings, notes and relationships."""
    restored = _guard(store.unmerge, merge_id)
    row = db.one("SELECT target_id FROM crm_merges WHERE id = ?", (merge_id,))
    duplicates.remember_split(restored.id, row["target_id"])
    return _brief(restored)
