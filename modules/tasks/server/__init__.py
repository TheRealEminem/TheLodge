"""Tasks: things to do, from anywhere. It listens for the shared "actions.found" contract, so any module that
finds action items (notes today, meetings tomorrow) feeds it without either knowing about the other, and it
links each task back to where it came from.
"""
from core.server import contracts
from core.server.module import Module

from . import routes, store

MODULE = Module(
    id="tasks",
    name="Tasks",
    router=routes.router,
    migrations=store.MIGRATIONS,
    subscribe={
        contracts.ACTIONS_FOUND: store.take_actions,
        contracts.ITEM_DELETED: store.source_deleted,
    },
    search=store.search,
    describe=store.describe,
)
