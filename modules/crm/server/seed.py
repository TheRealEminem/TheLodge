"""Fictional demo network so the app has something to show on first run.

Every record is created with source="demo" and can be removed again (DELETE /api/crm/admin/demo)."""
from datetime import UTC, date, datetime, time, timedelta

from core.server import db

from . import store

ME = "Jordan Reyes"

ORGS = {
    "Reyes Advisory": {"industry": "Advisory", "website": "reyes-advisory.example"},
    "Helio Cold Chain": {"industry": "Cold chain logistics", "website": "helio.example"},
    "Frostline Logistics": {"industry": "Refrigerated freight"},
    "Northwind Ventures": {"industry": "Venture capital"},
    "Kestrel Climate Fund": {"industry": "Climate venture capital"},
    "Blue Meridian Foods": {"industry": "Food distribution"},
    "Tidewater Robotics": {"industry": "Warehouse automation"},
    "Cascade Energy Storage": {"industry": "Thermal energy storage"},
    "Pinecrest University": {"industry": "Research university"},
    "Harborview Capital": {"industry": "Growth equity"},
    "Lumen Analytics": {"industry": "IoT sensors"},
    "Granite Peak Partners": {"industry": "Strategy consulting"},
    "Evergreen Agritech": {"industry": "Agtech"},
    "Solace Health Systems": {"industry": "Vaccine logistics"},
}

# name: (organization, title, location)
PEOPLE = {
    ME: ("Reyes Advisory", "Founder & Advisor", "Portland, OR"),
    "Maya Johnson": ("Reyes Advisory", "Analyst", "Portland, OR"),
    "Priya Nair": ("Helio Cold Chain", "CEO", "Oakland, CA"),
    "Marcus Webb": ("Helio Cold Chain", "CTO", "Oakland, CA"),
    "Lena Park": ("Helio Cold Chain", "Head of Operations", "Oakland, CA"),
    "Tom Albright": ("Frostline Logistics", "VP Partnerships", "Chicago, IL"),
    "Grace Okafor": ("Frostline Logistics", "COO", "Chicago, IL"),
    "Daniel Ruiz": ("Northwind Ventures", "Partner", "San Francisco, CA"),
    "Sofia Lindqvist": ("Northwind Ventures", "Principal", "San Francisco, CA"),
    "Amara Diallo": ("Kestrel Climate Fund", "Managing Partner", "Boston, MA"),
    "Ben Hartley": ("Kestrel Climate Fund", "Associate", "Boston, MA"),
    "Hannah Cole": ("Blue Meridian Foods", "Director of Supply Chain", "Seattle, WA"),
    "Raj Mehta": ("Blue Meridian Foods", "CFO", "Seattle, WA"),
    "Ethan Brooks": ("Tidewater Robotics", "Founder & CEO", "Baltimore, MD"),
    "Mei Tanaka": ("Tidewater Robotics", "Head of Product", "Baltimore, MD"),
    "Olivia Grant": ("Cascade Energy Storage", "CEO", "Denver, CO"),
    "Victor Salas": ("Cascade Energy Storage", "Chief Engineer", "Denver, CO"),
    "Ruth Feldman": ("Pinecrest University", "Professor, Refrigeration Engineering", "Madison, WI"),
    "Kofi Mensah": ("Pinecrest University", "PhD Researcher", "Madison, WI"),
    "Nathan Price": ("Harborview Capital", "Managing Director", "New York, NY"),
    "Claire Dubois": ("Harborview Capital", "Vice President", "New York, NY"),
    "Isabel Ortiz": ("Lumen Analytics", "CEO", "Austin, TX"),
    "Sam Whitaker": ("Lumen Analytics", "Solutions Architect", "Austin, TX"),
    "Laura Chen": ("Granite Peak Partners", "Partner", "Seattle, WA"),
    "Diego Fernandez": ("Granite Peak Partners", "Consultant", "Seattle, WA"),
    "Noah Patel": ("Evergreen Agritech", "Co-founder", "Sacramento, CA"),
    "Ava Robinson": ("Evergreen Agritech", "Co-founder", "Sacramento, CA"),
    "Elena Petrova": ("Solace Health Systems", "VP Global Distribution", "Atlanta, GA"),
    "James O'Connor": ("Solace Health Systems", "Procurement Lead", "Atlanta, GA"),
    "Chris Morgan": (None, "Angel investor", "Portland, OR"),
    "Tessa Wright": (None, "Board advisor", "Palo Alto, CA"),
}

TOPICS = [
    "Cold chain logistics",
    "Thermal energy storage",
    "Series A fundraising",
    "Warehouse automation",
    "Vaccine distribution",
    "IoT temperature monitoring",
    "Food waste reduction",
]

# (source, kind, target, strength)
EDGES = [
    (ME, "knows", "Priya Nair", 5), (ME, "knows", "Daniel Ruiz", 4), (ME, "knows", "Amara Diallo", 4),
    (ME, "knows", "Tom Albright", 3), (ME, "knows", "Hannah Cole", 4), (ME, "knows", "Ethan Brooks", 3),
    (ME, "knows", "Laura Chen", 4), (ME, "knows", "Chris Morgan", 5), (ME, "knows", "Tessa Wright", 4),
    (ME, "knows", "Ruth Feldman", 3), (ME, "knows", "Isabel Ortiz", 2), (ME, "knows", "Nathan Price", 2),
    (ME, "knows", "Olivia Grant", 3), (ME, "knows", "Noah Patel", 3),
    ("Priya Nair", "introduced_by", "Chris Morgan", 4), ("Amara Diallo", "introduced_by", "Daniel Ruiz", 3),
    ("Ethan Brooks", "introduced_by", "Tom Albright", 3), ("Olivia Grant", "introduced_by", "Ruth Feldman", 3),
    (ME, "advises", "Helio Cold Chain", 5), (ME, "advises", "Evergreen Agritech", 4),
    ("Tessa Wright", "advises", "Helio Cold Chain", 4), ("Ruth Feldman", "advises", "Cascade Energy Storage", 3),
    ("Laura Chen", "advises", "Solace Health Systems", 4), ("Chris Morgan", "advises", "Tidewater Robotics", 3),
    ("Northwind Ventures", "invested_in", "Helio Cold Chain", 4), ("Kestrel Climate Fund", "invested_in", "Cascade Energy Storage", 4),
    ("Kestrel Climate Fund", "invested_in", "Evergreen Agritech", 3), ("Chris Morgan", "invested_in", "Helio Cold Chain", 3),
    ("Harborview Capital", "invested_in", "Frostline Logistics", 4), ("Northwind Ventures", "invested_in", "Tidewater Robotics", 3),
    ("Helio Cold Chain", "partner_of", "Frostline Logistics", 4), ("Lumen Analytics", "partner_of", "Helio Cold Chain", 3),
    ("Blue Meridian Foods", "partner_of", "Frostline Logistics", 3), ("Tidewater Robotics", "partner_of", "Blue Meridian Foods", 2),
    ("Hannah Cole", "knows", "Elena Petrova", 4), ("Laura Chen", "knows", "Elena Petrova", 3),
    ("Daniel Ruiz", "knows", "Nathan Price", 3), ("Amara Diallo", "knows", "Olivia Grant", 4),
    ("Ethan Brooks", "knows", "Hannah Cole", 2), ("Isabel Ortiz", "knows", "Marcus Webb", 3),
    ("Ben Hartley", "knows", "Kofi Mensah", 2), ("Raj Mehta", "knows", "Nathan Price", 3),
    ("James O'Connor", "knows", "Hannah Cole", 3), ("Victor Salas", "knows", "Kofi Mensah", 3),
    ("Sofia Lindqvist", "knows", "Ben Hartley", 3),
    ("Marcus Webb", "reports_to", "Priya Nair", 4), ("Lena Park", "reports_to", "Priya Nair", 4),
    ("Ben Hartley", "reports_to", "Amara Diallo", 4), ("Sofia Lindqvist", "reports_to", "Daniel Ruiz", 4),
    ("Maya Johnson", "reports_to", ME, 5), ("Kofi Mensah", "reports_to", "Ruth Feldman", 4),
    ("Diego Fernandez", "reports_to", "Laura Chen", 3), ("Claire Dubois", "reports_to", "Nathan Price", 3),
    ("Sam Whitaker", "reports_to", "Isabel Ortiz", 3), ("Mei Tanaka", "reports_to", "Ethan Brooks", 4),
    ("Victor Salas", "reports_to", "Olivia Grant", 4), ("James O'Connor", "reports_to", "Elena Petrova", 3),
    ("IoT temperature monitoring", "part_of", "Cold chain logistics", 3),
    ("Vaccine distribution", "part_of", "Cold chain logistics", 3),
]

# (days ago, title, attendees, discussed, summary, action items)
MEETINGS = [
    (400, "Helio advisory kickoff", ["Priya Nair", "Marcus Webb"], ["Helio Cold Chain", "Cold chain logistics"],
     "Agreed scope for the advisory engagement: go-to-market for last-mile refrigerated delivery and a fundraising plan.",
     ["Jordan to send advisory agreement", "Priya to share the current pipeline"]),
    (380, "Intro call with Northwind", ["Daniel Ruiz"], ["Northwind Ventures", "Series A fundraising"],
     "Daniel walked through Northwind's climate thesis. Strong interest in logistics software with hardware attach.",
     ["Jordan to share Helio one-pager"]),
    (350, "Cascade thermal storage deep-dive", ["Olivia Grant", "Victor Salas", "Ruth Feldman"],
     ["Cascade Energy Storage", "Thermal energy storage"],
     "Technical review of Cascade's phase-change modules. Ruth flagged cycle-life testing as the key risk.",
     ["Victor to send test data", "Ruth to connect Cascade with her lab"]),
    (330, "Frostline partnership exploration", ["Tom Albright", "Grace Okafor", "Priya Nair"],
     ["Frostline Logistics", "Helio Cold Chain"],
     "Explored Helio software across Frostline's reefer fleet. Grace wants a 20-truck pilot first.",
     ["Priya to draft pilot terms"]),
    (300, "Kestrel fund strategy lunch", ["Amara Diallo", "Ben Hartley"],
     ["Kestrel Climate Fund", "Series A fundraising", "Thermal energy storage"],
     "Amara outlined Fund III priorities: thermal storage and food systems. Open to co-investing with Northwind.",
     []),
    (270, "Tidewater robotics demo", ["Ethan Brooks", "Mei Tanaka", "Tom Albright"],
     ["Tidewater Robotics", "Warehouse automation"],
     "Live demo of autonomous pallet movers in a -20C freezer. Frostline interested for its Chicago hub.",
     ["Tom to scope a site visit"]),
    (250, "Blue Meridian supply chain review", ["Hannah Cole", "Raj Mehta"],
     ["Blue Meridian Foods", "Food waste reduction", "Cold chain logistics"],
     "Blue Meridian loses ~6% of perishables in transit. Hannah wants better temperature visibility.",
     ["Jordan to introduce Lumen Analytics"]),
    (230, "Helio board prep", ["Priya Nair", "Tessa Wright", "Chris Morgan"],
     ["Helio Cold Chain", "Series A fundraising"],
     "Reviewed metrics ahead of the board meeting. Tessa pushed for a clearer enterprise pricing story.",
     ["Priya to revise pricing slide"]),
    (210, "Harborview catch-up", ["Nathan Price", "Claire Dubois"], ["Harborview Capital", "Frostline Logistics"],
     "Nathan shared Frostline's growth plans post-investment; Harborview looking at adjacent cold storage deals.",
     []),
    (190, "Lumen sensor pilot scoping", ["Isabel Ortiz", "Sam Whitaker", "Marcus Webb"],
     ["Lumen Analytics", "IoT temperature monitoring", "Helio Cold Chain"],
     "Scoped a sensor integration pilot between Lumen and Helio. Sam to own the API work.",
     ["Sam to share API docs", "Marcus to assign an engineer"]),
    (170, "Pinecrest research collaboration", ["Ruth Feldman", "Kofi Mensah"],
     ["Pinecrest University", "Thermal energy storage"],
     "Kofi's thesis on low-GWP refrigerants could inform Cascade's roadmap. Discussed a sponsored research agreement.",
     ["Jordan to raise with Olivia"]),
    (150, "Evergreen advisory session", ["Noah Patel", "Ava Robinson"],
     ["Evergreen Agritech", "Food waste reduction", "Kestrel Climate Fund"],
     "Worked through Evergreen's seed narrative. Kestrel is the natural lead.",
     ["Jordan to make Kestrel intro"]),
    (130, "Cascade follow-up", ["Olivia Grant"], ["Cascade Energy Storage", "Pinecrest University"],
     "Olivia keen on the Pinecrest collaboration; wants to revisit once cycle-life data is in.", []),
    (120, "Granite Peak strategy sync", ["Laura Chen", "Diego Fernandez"],
     ["Granite Peak Partners", "Solace Health Systems", "Vaccine distribution"],
     "Laura's team is advising Solace on last-mile vaccine distribution in hot climates.", []),
    (100, "Helio Series A pitch rehearsal", ["Priya Nair", "Marcus Webb", "Daniel Ruiz", "Sofia Lindqvist"],
     ["Helio Cold Chain", "Series A fundraising", "Northwind Ventures"],
     "Dry run of the Series A pitch. Northwind signalled intent to lead if unit economics hold.",
     ["Priya to tighten unit economics", "Sofia to send diligence list"]),
    (85, "Blue Meridian x Frostline intro", ["Hannah Cole", "Tom Albright"],
     ["Blue Meridian Foods", "Frostline Logistics", "Cold chain logistics"],
     "Intro between Hannah and Tom on consolidating Blue Meridian's Pacific Northwest freight.", []),
    (70, "Tidewater investor update", ["Ethan Brooks", "Chris Morgan"], ["Tidewater Robotics"],
     "Tidewater closed two new freezer-warehouse customers. Chris considering a follow-on.", []),
    (55, "Kestrel diligence call: Evergreen", ["Amara Diallo", "Ben Hartley", "Noah Patel"],
     ["Kestrel Climate Fund", "Evergreen Agritech"],
     "Kestrel diligence on Evergreen's yield data. Ben requested customer references.",
     ["Noah to send three customer references"]),
    (42, "Helio ops review", ["Priya Nair", "Lena Park"], ["Helio Cold Chain"],
     "Lena presented on-time delivery at 97%. Spoilage claims down 40% since the Lumen integration.", []),
    (30, "Lunch with Laura Chen", ["Laura Chen"], ["Solace Health Systems", "Vaccine distribution"],
     "Laura thinks Solace needs a cold chain software partner. Suggested Helio could be a fit.",
     ["Jordan to ask Laura for an intro to Elena Petrova"]),
    (21, "Northwind portfolio day", ["Daniel Ruiz", "Sofia Lindqvist", "Ethan Brooks"],
     ["Northwind Ventures", "Tidewater Robotics", "Warehouse automation"],
     "Northwind portfolio day. Ethan presented Tidewater's roadmap; strong interest from Blue Meridian.", []),
    (12, "Helio x Lumen pilot results", ["Priya Nair", "Marcus Webb", "Sam Whitaker"],
     ["Helio Cold Chain", "Lumen Analytics", "IoT temperature monitoring"],
     "Pilot hit all success criteria. Moving to a commercial agreement next quarter.",
     ["Marcus to draft integration SLA"]),
    (6, "Coffee with Chris Morgan", ["Chris Morgan"], ["Tidewater Robotics", "Helio Cold Chain"],
     "Chris is raising a small climate hardware fund and asked for deal flow.", []),
    (2, "Blue Meridian quarterly", ["Hannah Cole", "Raj Mehta"],
     ["Blue Meridian Foods", "Food waste reduction", "Vaccine distribution"],
     "Transit losses down to 4%. Hannah mentioned she worked with Elena Petrova at Solace and offered an intro.",
     ["Hannah to intro Jordan to Elena Petrova"]),
]

# (days ago, title, doc type, author, mentions)
DOCUMENTS = [
    (340, "Cascade technical memo", "Memo", "Victor Salas", ["Thermal energy storage", "Cascade Energy Storage"]),
    (148, "Evergreen advisory agreement", "Contract", ME, ["Evergreen Agritech"]),
    (95, "Helio Series A deck", "Pitch deck", "Priya Nair", ["Helio Cold Chain", "Northwind Ventures"]),
    (60, "Cold chain market map", "Research", ME,
     ["Helio Cold Chain", "Frostline Logistics", "Lumen Analytics", "Tidewater Robotics", "Cold chain logistics"]),
]

NOTES = {
    "Priya Nair": ["Prefers async updates by email; sends a Friday metrics digest."],
    "Chris Morgan": ["Invests pre-seed in climate hardware; typical check $50-150k."],
    "Hannah Cole": ["Worked with Elena Petrova at a previous company; offered a warm intro."],
    "Amara Diallo": ["Kestrel Fund III focus: thermal storage and food systems."],
    "Olivia Grant": ["Asked to reconnect once cycle-life test data is available."],
    "Tom Albright": ["Looking for sensor partners for a reefer fleet retrofit."],
}


def _days_ago(n: int) -> datetime:
    d = datetime.now(UTC).date() - timedelta(days=n)
    return datetime.combine(d, time(16, 0), tzinfo=UTC)


def has_data() -> bool:
    return bool(db.one("SELECT count(*) AS n FROM crm_entities")["n"])


def has_demo() -> bool:
    return db.one("SELECT 1 AS x FROM crm_entities WHERE source = 'demo' LIMIT 1") is not None


def seed_demo() -> dict:
    ids: dict[str, str] = {}
    edges = 0
    with db.connect() as c:
        has_self = bool(c.execute("SELECT 1 FROM crm_entities WHERE is_self = 1").fetchone())

        def add(kind: str, name: str, **kw) -> str:
            e = store.create_entity(kind, name, source="demo", tags=["demo"], conn=c, **kw)
            ids[name] = e.id
            return e.id

        def link(source: str, kind: str, target: str, strength: int = 3, **kw) -> None:
            nonlocal edges
            store.create_edge(ids[source], ids[target], kind, strength=strength, source="demo", conn=c, **kw)
            edges += 1

        for name, attrs in ORGS.items():
            add("organization", name, attributes=attrs)
        for name in TOPICS:
            add("topic", name)
        for name, (_, title, location) in PEOPLE.items():
            slug = name.lower().replace(" ", ".").replace("'", "")
            add("person", name, is_self=(name == ME and not has_self),
                attributes={"title": title, "location": location, "email": f"{slug}@example.com"})

        today = date.today()
        for name, (org, title, _) in PEOPLE.items():
            if org:
                link(name, "works_at", org, 4, properties={"title": title},
                     started_at=today - timedelta(days=400 + sum(map(ord, name)) % 1500))
        for s, kind, t, strength in EDGES:
            link(s, kind, t, strength)

        for days, title, attendees, discussed, summary, actions in MEETINGS:
            m_id = add("meeting", title, occurred_at=_days_ago(days), summary=summary,
                       attributes={"action_items": actions, "location": "Video call" if days % 2 else "In person"})
            for person in [ME, *attendees]:
                link(person, "attended", title, 3, evidence_id=m_id)
            for thing in discussed:
                link(thing, "discussed_in", title, 3, evidence_id=m_id)

        for days, title, doc_type, author, mentions in DOCUMENTS:
            d_id = add("document", title, occurred_at=_days_ago(days), attributes={"doc_type": doc_type})
            link(author, "authored", title, 4)
            for thing in mentions:
                link(thing, "mentioned_in", title, 3, evidence_id=d_id)

        for name, notes in NOTES.items():
            for body in notes:
                store.add_note(ids[name], body, source="demo", occurred_at=_days_ago(40), conn=c)
    return {"entities": len(ids), "relationships": edges}


def remove_demo() -> int:
    n = db.execute("DELETE FROM crm_entities WHERE source = 'demo'")
    db.execute("DELETE FROM crm_fts WHERE id NOT IN (SELECT id FROM crm_entities)")
    store._touch()
    return n
