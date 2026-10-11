"""The tasks API, mounted at /api/tasks."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.server import events, module

from . import store

router = APIRouter()


class TaskIn(BaseModel):
    text: str


class TaskPatch(BaseModel):
    done: bool


@router.get("")
def list_tasks():
    out = []
    for task in store.all_tasks():
        source = module.describe(task["source_ref"]) if task["source_ref"] else None
        out.append({**task, "source": source})
    return out


@router.get("/count")
def count():
    return {"open": store.open_count()}


@router.post("", status_code=201)
def create_task(body: TaskIn):
    if not body.text.strip():
        raise HTTPException(400, "A task needs some text")
    task_id = store.create(body.text.strip())
    events.publish("tasks.changed", {})
    return {"id": task_id}


@router.patch("/{task_id}")
def patch_task(task_id: str, body: TaskPatch):
    if not store.set_done(task_id, body.done):
        raise HTTPException(404, "Task not found")
    events.publish("tasks.changed", {})
    return {"ok": True}


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str):
    store.delete(task_id)
    events.publish("tasks.changed", {})
