"""Roundups, mounted under /api/crm/roundups (see roundups.py)."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import roundups

router = APIRouter(prefix="/roundups")

MEDIA = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "pdf": "application/pdf",
         "md": "text/markdown; charset=utf-8"}


class New(BaseModel):
    title: str | None = None
    event: str | None = None
    audience: str | None = None
    group: str | None = None
    people: list[str] = Field(default_factory=list, max_length=roundups.MAX_PEOPLE)


class Change(BaseModel):
    title: str | None = None
    event: str | None = None
    audience: str | None = None
    people: list[str] | None = Field(default=None, max_length=roundups.MAX_PEOPLE)


class Add(BaseModel):
    group: str | None = None
    people: list[str] = Field(default_factory=list, max_length=roundups.MAX_PEOPLE)


class Export(BaseModel):
    format: Literal["docx", "pdf", "md"]


def _guard(fn, *args):
    try:
        return fn(*args)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except roundups.RoundupError as e:
        raise HTTPException(422, str(e)) from e


@router.get("")
def listing():
    return roundups.listing()


@router.get("/groups")
def groups():
    """The organizations, topics and tags a roundup can start from."""
    return roundups.groups()


@router.post("", status_code=201)
def create(body: New):
    return _guard(roundups.create, body.title, body.event, body.audience, body.group, body.people)


@router.get("/{rid}")
def detail(rid: str):
    return _guard(roundups.detail, rid)


@router.patch("/{rid}")
def update(rid: str, body: Change):
    return _guard(roundups.update, rid, body.model_dump(exclude_unset=True))


@router.post("/{rid}/people")
def add_people(rid: str, body: Add):
    """Adds a group's people, or the people named, after the ones already on it."""
    return _guard(roundups.add_people, rid, body.group, body.people)


@router.delete("/{rid}", status_code=204)
def delete(rid: str):
    _guard(roundups.delete, rid)
    return Response(status_code=204)


@router.post("/{rid}/prepare")
def prepare(rid: str):
    """Writes the packet in the background: a line or two on each person, then the opening."""
    return _guard(roundups.prepare, rid)


@router.post("/{rid}/export")
def export(rid: str, body: Export):
    """Saves the prepared packet as a file in the roundup's folder."""
    return _guard(roundups.export, rid, body.format)


@router.get("/{rid}/files/{name}")
def download(rid: str, name: str):
    path = _guard(roundups.file_path, rid, name)
    return FileResponse(path, media_type=MEDIA[path.suffix.lstrip(".")], filename=path.name)
