"""Automatic capture, mounted under /api/crm/capture: what Granola and the calendars have done, trying a key or an
address, syncing now, and taking back everything one of them brought in."""
from fastapi import APIRouter, HTTPException

from core.server import jobs, schedule

from . import calendar_sync, capture, granola

router = APIRouter(prefix="/capture")


def _status(name: str, configured: bool) -> dict:
    state = capture.get_state(name)
    return {"configured": configured, **{k: state.get(k) for k in ("last_run_at", "last_ok_at", "last_counts", "error", "key_problem", "calendars")}}


@router.get("")
def status():
    return {"granola": _status("granola", granola.configured()), "calendar": _status("calendar", calendar_sync.configured()),
            "sources": [capture.preview(o) for o in capture.ORIGINS]}


@router.post("/granola/test")
def test_granola():
    try:
        return granola.test()
    except granola.GranolaError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/calendar/test")
def test_calendar():
    try:
        return calendar_sync.test()
    except calendar_sync.CalendarError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/sync", status_code=202)
def sync_now():
    """Run both now rather than at their next turn. Anything not set up does nothing."""
    queued = []
    if granola.configured():
        queued.append(jobs.enqueue("crm", "granola_sync", schedule.TARGET))
    if calendar_sync.configured():
        queued.append(jobs.enqueue("crm", "calendar_sync", schedule.TARGET))
    return {"queued": len(queued)}


@router.get("/{origin}/preview")
def preview(origin: str):
    try:
        return capture.preview(origin)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/{origin}/remove")
def remove(origin: str):
    try:
        return capture.remove(origin)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
