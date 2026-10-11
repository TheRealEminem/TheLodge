"""The __Name__ API, mounted at /api/__id__."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.server import contracts, events, links

from . import store

router = APIRouter()


class ItemIn(BaseModel):
    title: str


@router.get("")
def list_items():
    return store.all_items()


@router.post("", status_code=201)
def create_item(body: ItemIn):
    if not body.title.strip():
        raise HTTPException(400, "Give it a title")
    item_id = store.create(body.title.strip())
    events.publish("__id__.item.created", {"id": item_id})
    return {"id": item_id}


@router.get("/{item_id}")
def get_item(item_id: str):
    item = store.get(item_id)
    if not item:
        raise HTTPException(404, "Not found")
    return item


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: str):
    ref = links.ref("__id__", item_id)
    store.delete(item_id)
    events.publish(contracts.ITEM_DELETED, {"ref": ref})
    links.forget(ref)
