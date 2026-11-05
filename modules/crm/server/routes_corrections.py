"""Hats, and putting right what an import got wrong, mounted under /api/crm (see hats.py and corrections.py)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import corrections, hats, profiles, store

router = APIRouter()


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (store.NotFound, LookupError) as e:
        raise HTTPException(404, str(e)) from e
    except (hats.HatError, corrections.CorrectionError, profiles.ProfileError) as e:
        raise HTTPException(422, str(e)) from e


# ── Hats ──────────────────────────────────────────────────────────────

class HatIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    title: str | None = None
    org_id: str | None = None


class HatPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    title: str | None = None
    org_id: str | None = None


class ActiveIn(BaseModel):
    id: str | None = None


class PlaceIn(BaseModel):
    ids: list[str] = Field(max_length=2000)
    how: str | None = None


@router.get("/hats")
def list_hats():
    return hats.listing()


@router.post("/hats", status_code=201)
def create_hat(body: HatIn):
    _guard(hats.create, body.name, title=body.title, org_id=body.org_id)
    return hats.listing()


@router.put("/hats/active")
def wear(body: ActiveIn):
    _guard(hats.set_active, body.id)
    return hats.listing()


@router.patch("/hats/{hat_id}")
def change_hat(hat_id: str, body: HatPatch):
    _guard(hats.update, hat_id, **body.model_dump(exclude_unset=True))
    return hats.listing()


@router.delete("/hats/{hat_id}")
def delete_hat(hat_id: str):
    _guard(hats.delete, hat_id)
    return hats.listing()


@router.post("/hats/{hat_id}/place")
def place(hat_id: str, body: PlaceIn):
    """Put records in a hat ("you"), take them out ("no"), or go back to what they're linked to (null)."""
    return {"changed": _guard(hats.place, hat_id, body.ids, body.how)}


@router.get("/entities/{entity_id}/hats")
def hats_of(entity_id: str):
    return _guard(hats.of, entity_id)


# ── Sources on a record ───────────────────────────────────────────────

class DetachIn(BaseModel):
    to_id: str | None = None
    new_name: str | None = Field(default=None, max_length=300)


class RenameText(BaseModel):
    old: str = Field(min_length=1, max_length=300)
    new: str = Field(min_length=1, max_length=300)


class CheckIn(BaseModel):
    entity_id: str
    evidence_id: str


class OverviewIn(BaseModel):
    body: str = Field(min_length=1)


@router.get("/entities/{entity_id}/sources/{evidence_id}")
def source_preview(entity_id: str, evidence_id: str):
    """What taking this meeting or document off the record would take with it."""
    return _guard(corrections.preview, entity_id, evidence_id)


@router.post("/entities/{entity_id}/sources/{evidence_id}/detach")
def detach(entity_id: str, evidence_id: str, body: DetachIn):
    """This meeting or document isn't about them: remove it, or give it to who it's really about."""
    return _guard(corrections.detach, entity_id, evidence_id, to_id=body.to_id, new_name=body.new_name)


@router.post("/entities/{entity_id}/reports/{inbox_id}/unlink", status_code=204)
def unlink_report(entity_id: str, inbox_id: str):
    """A report about someone else named a different person of this name."""
    _guard(corrections.unlink_report, entity_id, inbox_id)


@router.get("/entities/{entity_id}/corrections")
def corrections_of(entity_id: str):
    return corrections.of(entity_id)


@router.post("/corrections/{correction_id}/undo")
def undo(correction_id: str):
    return _guard(corrections.undo, correction_id)


@router.post("/entities/{entity_id}/rename-text")
def rename_text(entity_id: str, body: RenameText):
    return {"changed": _guard(corrections.rename_text, entity_id, body.old, body.new)}


@router.get("/link-checks")
def link_checks():
    return corrections.checks()


@router.post("/link-checks/right", status_code=204)
def link_is_right(body: CheckIn):
    corrections.looks_right(body.entity_id, body.evidence_id)


@router.put("/people/{person_id}/overview")
def write_overview(person_id: str, body: OverviewIn):
    """Your own words for their overview. The AI leaves it alone until you ask it to write one again."""
    return _guard(profiles.set_overview, person_id, body.body)
