"""People: the relationship CRM. Who you know, how well, and what you know about them, kept as a graph of
people, organizations, meetings, documents and topics.

Everything is a node (crm_entities) or an edge (crm_relationships). See store.py for the tables.
"""
from core.server.module import Module

from . import routes, store

MODULE = Module(
    id="crm",
    name="People",
    router=routes.router,
    migrations=store.MIGRATIONS,
    search=store.search,
    describe=store.describe,
)
