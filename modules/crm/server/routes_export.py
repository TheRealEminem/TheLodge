"""Quick export of one person or organization, mounted under /api/crm (see quick_export.py)."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import quick_export

router = APIRouter()
MEDIA = {"pdf": "application/pdf", "md": "text/markdown; charset=utf-8"}


class SaveIn(BaseModel):
    format: Literal["md", "pdf"]


def _guard(fn, *args):
    try:
        return fn(*args)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except quick_export.ExportError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/entities/{entity_id}/export")
def export(entity_id: str):
    """What's on file about them as Markdown, to copy or to look over before saving."""
    return _guard(quick_export.build, entity_id)


@router.post("/entities/{entity_id}/export")
def save(entity_id: str, body: SaveIn):
    """Saves it as a Markdown or PDF file in the data folder's crm/exports/."""
    return _guard(quick_export.save, entity_id, body.format)


@router.get("/exports/{name}")
def download(name: str):
    path = _guard(quick_export.file_path, name)
    return FileResponse(path, media_type=MEDIA[path.suffix.lstrip(".")], filename=path.name)
