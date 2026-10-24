"""The shared Google Sheet, mounted under /api/crm/sheet: how the last sync went, the script to paste into the sheet,
trying the link, syncing now, and your answer when a tab was held back."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.server import jobs, schedule

from . import capture, sheet_script, sheet_sync

router = APIRouter(prefix="/sheet")


@router.get("")
def status():
    state = capture.get_state("sheet")
    return {"configured": sheet_sync.configured(), "locked": sheet_sync.locked(), "script_version": sheet_script.VERSION,
            **{k: state.get(k) for k in ("last_run_at", "last_ok_at", "last_counts", "error", "link_problem", "spreadsheet", "held", "decision")}}


@router.get("/script")
def script():
    return {"text": sheet_script.SCRIPT, "version": sheet_script.VERSION}


@router.post("/test")
def test():
    try:
        return sheet_sync.test()
    except sheet_sync.SheetError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/sync", status_code=202)
def sync_now():
    if not sheet_sync.configured():
        raise HTTPException(422, "Paste the sheet's script link first.")
    return {"job": jobs.enqueue("crm", "sheet_sync", schedule.TARGET)}


class Decision(BaseModel):
    choice: Literal["apply", "restore"]


@router.post("/decide", status_code=202)
def decide(body: Decision):
    sheet_sync.decide(body.choice)
    return {"job": jobs.enqueue("crm", "sheet_sync", schedule.TARGET)}
