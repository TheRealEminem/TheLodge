"""Runs inside DynaCRM's own image (see scripts/parity-sheets.py): its SheetImporter over the recorded mappings, in a
scratch Postgres database. Prints the per-sheet stats and every record and line as JSON."""
import asyncio, json, os, sys
os.environ["DATABASE_URL"] = "postgresql+psycopg://dynacrm:dynacrm@host.docker.internal:5433/dynacrm_sheets"
os.environ["DB_NULLPOOL"] = "true"
os.environ["EXTRACTOR"] = "heuristic"
from sqlalchemy import select, text
from app.db import SessionLocal, engine
from app.models import Base, Entity, Relationship
from app.services.documents import parse_spreadsheet
from app.services.spreadsheets import SheetImporter, SheetMapping
from app.services.edges import upsert_edge

cfg = json.load(open("/work/config.json"))
mappings = json.load(open("/work/mappings.json"))

async def main():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        me = Entity(kind="person", name=cfg["me"], is_self=True, source="manual"); cc = Entity(kind="organization", name="Cinder Labs", source="manual")
        s.add_all([me, cc]); await s.flush()
        await upsert_edge(s, me.id, cc.id, "works_at", source="manual")
        for n in cfg["team"]:
            p = Entity(kind="person", name=n, source="manual"); s.add(p); await s.flush()
            await upsert_edge(s, p.id, cc.id, "works_at", source="manual")
        await s.commit()
    out = {}
    for title in cfg["order"]:
        async with SessionLocal() as s:
            owner = await s.scalar(select(Entity).where(Entity.is_self.is_(True)))
            edge = await s.scalar(select(Relationship).where(Relationship.source_id == owner.id, Relationship.kind == "works_at"))
            team = (await s.scalars(select(Entity).join(Relationship, Relationship.source_id == Entity.id).where(
                Relationship.target_id == edge.target_id, Relationship.kind == "works_at", Relationship.ended_at.is_(None), Entity.id != owner.id).limit(12))).all()
            imp = SheetImporter(s, owner, [*team, owner], source="spreadsheet")
            for sh in parse_spreadsheet(title + ".xlsx", open(f"/files/{title}.xlsx", "rb").read()):
                await imp.import_sheet(sh, SheetMapping.model_validate(mappings[title][sh.name]), None)
            await s.commit()
            out[title] = imp.stats
    async with SessionLocal() as s:
        ents = sorted((e.kind, e.name) for e in (await s.scalars(select(Entity))).all())
        rels = sorted((r.kind, str(r.source_id), str(r.target_id)) for r in (await s.scalars(select(Relationship))).all())
        names = {str(e.id): e.name for e in (await s.scalars(select(Entity))).all()}
    print(json.dumps({"stats": out, "entities": ents, "edges": sorted((k, names[a], names[b]) for k, a, b in rels)}))
asyncio.run(main())
