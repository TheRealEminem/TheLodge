"""Tasks: all of your work, from anywhere. Projects with milestones, work items with subtasks and blockers, and
updates (since step 2; Traverse PLAN.md chunk 2). It listens for the shared "actions.found" contract, so any module
that finds action items (notes today, meetings tomorrow) feeds it without either knowing about the other, and it
links each task back to where it came from. Work kept somewhere else too (a Plane work item) arrives and follows
through the shared work.* contracts (synced.py), again without this module knowing where that is.
"""
from core.server import contracts
from core.server.module import Module

from . import hooks, routes, store, synced

MODULE = Module(
    id="tasks",
    name="Projects",
    router=routes.router,
    migrations=store.MIGRATIONS,
    subscribe={
        contracts.ACTIONS_FOUND: hooks.take_actions,
        contracts.ITEM_DELETED: hooks.source_deleted,
        contracts.WORK_PROJECT_ARRIVED: synced.project_arrived,
        contracts.WORK_ARRIVED: synced.arrived,
        contracts.WORK_UPDATED_ELSEWHERE: synced.updated,
        contracts.WORK_REMOVED_ELSEWHERE: synced.removed,
    },
    search=hooks.search,
    describe=hooks.describe,
    export=hooks.export,
    count=hooks.count,
)
