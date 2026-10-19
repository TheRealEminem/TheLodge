"""Research flags, mounted under /api/crm: who has nothing on file, the brief for a deep-research tool, and what
you decided about a flag."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import gemini_research, research

router = APIRouter()


class ResearchAction(BaseModel):
    action: Literal["snooze", "dismiss", "restore"]
    days: int = Field(default=research.SNOOZE_DAYS, ge=1, le=365)


def _guard(fn, *args):
    try:
        return fn(*args)
    except research.ResearchError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/research")
def list_research(state: Literal["needed", "snoozed", "dismissed", "name_needed"] = "needed",
                  limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    """People with no summary and no long-form research, the ones who matter most first."""
    return research.listing(state, limit, offset)


@router.get("/people/{person_id}/research")
def person_research(person_id: str):
    return _guard(research.state_of, person_id)


@router.post("/people/{person_id}/research")
def set_research(person_id: str, body: ResearchAction):
    """Snooze a flag, dismiss it ("not worth researching"), or bring it back."""
    return _guard(research.set_status, person_id, body.action, body.days)


@router.get("/people/{person_id}/research/brief")
def research_brief(person_id: str):
    """A prompt to paste into a deep-research tool. Nothing is sent from here."""
    return {"text": _guard(research.brief, person_id)}


# ── The Lodge researching people itself, with Gemini ─────────────────

class RunIn(BaseModel):
    person_ids: list[str] = Field(min_length=1, max_length=200)
    level: Literal["quick", "better", "best"] = "quick"
    batch: bool = True


def _run_guard(fn, *args):
    try:
        return fn(*args)
    except gemini_research.ResearchRunError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/research/gemini")
def gemini_overview():
    """The levels with what a person typically costs at each, the month's budget and spend, and recent runs."""
    return gemini_research.overview()


@router.post("/research/gemini", status_code=202)
def gemini_start(body: RunIn):
    """Research these people with Gemini: as many as fit in what's left of the month's budget. Each report waits
    in the Inbox for your OK."""
    return _run_guard(gemini_research.start, body.person_ids, body.level, body.batch)


@router.get("/people/{person_id}/research/gemini")
def gemini_run(person_id: str):
    return {"run": gemini_research.run_of(person_id)}


@router.post("/research/gemini/{run_id}/cancel")
def gemini_cancel(run_id: str):
    return _run_guard(gemini_research.cancel, run_id)


@router.post("/research/gemini/{run_id}/retry", status_code=202)
def gemini_retry(run_id: str):
    return _run_guard(gemini_research.retry, run_id)
