"""Pictures, mounted under /api/crm (see pictures.py)."""
from fastapi import APIRouter, HTTPException, Request, Response

from core.server import jobs

from . import pictures, store

router = APIRouter()
LOOKUP_TARGET = "pictures"


@router.get("/pictures")
def who_has_one():
    """{id: version} for everyone with a picture; the page asks once and again after changes."""
    return pictures.versions()


@router.get("/pictures/lookup")
def lookup_state():
    return {"allowed": pictures.blocked() is None, "reason": pictures.blocked(), "job": jobs.latest("crm", [LOOKUP_TARGET]).get(LOOKUP_TARGET)}


@router.post("/pictures/lookup", status_code=202)
def look_up_everyone():
    """Ask Gravatar about everyone with an email and no picture, in the background. Needs the setting on."""
    if (why := pictures.blocked()):
        raise HTTPException(422, why)
    return {"job": jobs.enqueue("crm", "pictures_lookup", LOOKUP_TARGET)}


@router.get("/pictures/{entity_id}")
def picture(entity_id: str, request: Request):
    found = pictures.get(entity_id)
    if found is None:
        raise HTTPException(404, "No picture")
    data, mime, version = found
    headers = {"ETag": f'"{version}"', "Cache-Control": "private, max-age=86400"}   # the page adds ?v=<version>
    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=mime, headers=headers)


@router.put("/pictures/{entity_id}", status_code=204)
async def set_picture(entity_id: str, request: Request):
    """The picture itself as the request body (the page has already made it a small square)."""
    data = await request.body()
    try:
        pictures.put(entity_id, data)
    except store.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except pictures.PictureError as e:
        raise HTTPException(422, str(e)) from e
    return Response(status_code=204)


@router.delete("/pictures/{entity_id}", status_code=204)
def remove_picture(entity_id: str):
    pictures.remove(entity_id)
    return Response(status_code=204)


@router.post("/people/{entity_id}/picture/lookup")
def look_up_one(entity_id: str):
    """Ask Gravatar about this one person. {"found": false} is a normal answer: they just don't have one there."""
    try:
        return {"found": pictures.look_up(entity_id)}
    except store.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except pictures.PictureError as e:
        raise HTTPException(422, str(e)) from e
