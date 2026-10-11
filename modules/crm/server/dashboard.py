from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel
from core.server import db

from .schemas import EntitySummary, OrgRow, PersonRow
from .connections import sort_key
from . import views

RECONNECT_AFTER_DAYS = 60
ACTIVITY_WEEKS = 26
LIST = 8


class MeetingCard(BaseModel):
    meeting: EntitySummary
    attendees: list[EntitySummary]
    discussed: list[EntitySummary]


class WeekActivity(BaseModel):
    week: date
    meetings: int


class Dashboard(BaseModel):
    me: EntitySummary | None
    counts: dict[str, int]
    relationships: int
    pending_reviews: int
    tiers: dict[str, int]
    strong: list[PersonRow]
    working: list[PersonRow]
    reconnect: list[PersonRow]
    lit_up: list[PersonRow]
    key_orgs: list[OrgRow]
    recent_meetings: list[MeetingCard]
    weekly_activity: list[WeekActivity]


def build_dashboard(me_id: str | None = None) -> Dashboard:
    now = datetime.now(UTC)
    counts = {r["kind"]: r["n"] for r in db.query("SELECT kind, count(*) AS n FROM crm_entities GROUP BY kind")}
    rel_count = db.one("SELECT count(*) AS n FROM crm_relationships")["n"]
    pending = db.one("SELECT count(*) AS n FROM crm_inbox WHERE status IN ('pending', 'processing', 'review')")["n"]

    v = views.get(me_id)
    ents, conns = v.snap.entities, v.conns
    ranked = sorted(conns, key=lambda pid: sort_key(conns[pid], ents[pid].name))
    tiers: dict[str, int] = {}
    for c in conns.values():
        tiers[c.tier] = tiers.get(c.tier, 0) + 1

    def rows(ids) -> list[PersonRow]:
        return [v.person_row(pid) for pid in list(ids)[:LIST]]

    cutoff = now - timedelta(days=RECONNECT_AFTER_DAYS)
    reconnect = [
        pid for pid in ranked
        if conns[pid].tier in ("strong", "working") and conns[pid].last_met_at and conns[pid].last_met_at < cutoff
    ]
    # Newest first: who your latest meetings and documents brought into view.
    lit = [pid for pid in conns if conns[pid].tier in ("light", "indirect") and conns[pid].last_signal_at]
    lit.sort(key=lambda pid: (conns[pid].last_signal_at, conns[pid].score), reverse=True)

    org_rows = [v.org_row(oid) for oid in v.orgs]
    key_orgs = sorted(
        (r for r in org_rows if r.known and not r.mine),
        key=lambda r: (-r.known, r.org.name.lower()),
    )[:6]

    meetings = sorted(
        (m for m in v.snap.of_kind("meeting") if m.occurred_at and m.occurred_at <= now + timedelta(days=1)),
        key=lambda m: m.occurred_at,  # type: ignore[arg-type,return-value]
        reverse=True,
    )[:6]

    def people_in(ids) -> list[EntitySummary]:
        people = [i for i in ids if ents[i].kind == "person" and not ents[i].is_self]
        return [v.summary(i) for i in sorted(people, key=lambda i: sort_key(conns[i], ents[i].name))]

    cards = [
        MeetingCard(
            meeting=v.summary(m.id),
            attendees=people_in(v.ix.attendees.get(m.id, set())),
            discussed=people_in(v.ix.discussed.get(m.id, set()) - v.ix.attendees.get(m.id, set())),
        )
        for m in meetings
    ]

    start = (now - timedelta(weeks=ACTIVITY_WEEKS - 1)).date()
    start = start - timedelta(days=start.weekday())  # Monday
    per_week: dict[date, int] = {}
    for m in v.snap.of_kind("meeting"):
        if m.occurred_at and start <= m.occurred_at.date() and m.occurred_at <= now:
            d = m.occurred_at.date()
            wk = d - timedelta(days=d.weekday())
            per_week[wk] = per_week.get(wk, 0) + 1

    return Dashboard(
        me=v.summary(v.me.id) if v.me else None,
        counts=counts,
        relationships=rel_count,
        pending_reviews=pending,
        tiers=tiers,
        strong=rows(p for p in ranked if conns[p].tier == "strong"),
        working=rows(p for p in ranked if conns[p].tier == "working"),
        reconnect=rows(reconnect),
        lit_up=rows(lit),
        key_orgs=key_orgs,
        recent_meetings=cards,
        weekly_activity=[
            WeekActivity(week=start + timedelta(weeks=i), meetings=per_week.get(start + timedelta(weeks=i), 0))
            for i in range(ACTIVITY_WEEKS)
        ],
    )
