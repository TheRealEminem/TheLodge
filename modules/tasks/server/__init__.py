"""Tasks: all of your work, from anywhere. Projects with milestones, work items with subtasks and blockers, and
updates (since step 2; Traverse PLAN.md chunk 2). It listens for the shared "actions.found" contract, so any module
that finds action items (notes today, meetings tomorrow) feeds it without either knowing about the other, and it
links each task back to where it came from. Work kept somewhere else too (a Plane work item) arrives and follows
through the shared work.* contracts (synced.py), again without this module knowing where that is. The AI drafts a
project's status update and breaks a task into subtasks, in a job, for you to edit, post or drop (drafts.py). Claude can
see your plate, find and add tasks, and propose sending one, through the host's MCP server (tools.py). Its part of the
day's briefing (Muster) is in briefing.py.
"""
from core.server import contracts
from core.server.module import Module

from . import briefing, drafts, hooks, routes, store, synced, tools

MODULE = Module(
    id="tasks",
    name="Projects",
    router=routes.router,
    migrations=store.MIGRATIONS,
    jobs={drafts.KIND: drafts.write},
    lanes={drafts.KIND: drafts.lane},
    subscribe={
        contracts.ACTIONS_FOUND: hooks.take_actions,
        contracts.ITEM_DELETED: hooks.source_deleted,
        contracts.WORK_PROJECT_ARRIVED: synced.project_arrived,
        contracts.WORK_ARRIVED: synced.arrived,
        contracts.WORK_UPDATED_ELSEWHERE: synced.updated,
        contracts.WORK_REMOVED_ELSEWHERE: synced.removed,
        contracts.WORK_MARKED_DONE: briefing.marked_done,
    },
    search=hooks.search,
    describe=hooks.describe,
    export=hooks.export,
    count=hooks.count,
    tools=tools.TOOLS,
    brief=briefing.brief,
)
