"""Overviews and questions about a person, mounted under /api/crm (see profiles.py)."""
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from . import profiles

router = APIRouter()


class Ask(BaseModel):
    question: str


def _guard(fn, *args):
    try:
        return fn(*args)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except profiles.ProfileError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/people/{person_id}/overview")
def overview(person_id: str):
    """Their overview, whether it's up to date, and the work on it. A missing or out-of-date one is asked for."""
    return _guard(profiles.overview_state, person_id)


@router.post("/people/{person_id}/overview")
def redo_overview(person_id: str):
    """Write it again now, even if nothing changed."""
    return _guard(profiles.redo_overview, person_id)


@router.get("/people/{person_id}/questions")
def questions(person_id: str):
    return _guard(profiles.questions, person_id)


@router.post("/people/{person_id}/questions", status_code=201)
def ask(person_id: str, body: Ask):
    """Ask something about them. The answer is worked out in the background and appears on the question."""
    return _guard(profiles.ask, person_id, body.question)


@router.delete("/people/{person_id}/questions", status_code=204)
def clear(person_id: str):
    _guard(profiles.clear, person_id)
    return Response(status_code=204)


@router.post("/questions/{question_id}/retry")
def retry(question_id: str):
    return _guard(profiles.retry, question_id)


@router.get("/overviews")
def coverage():
    """How many of your people have an overview so far."""
    return profiles.coverage()
