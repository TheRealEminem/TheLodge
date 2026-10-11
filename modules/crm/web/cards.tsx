// The cards a profile is made of.
import { Suspense, lazy, useState } from "react";
import { CalendarIcon, ChevronRightIcon, NetworkIcon, CloseIcon, DocIcon, ExternalIcon, MailIcon, MapPinIcon, PhoneIcon, PlusIcon, TrashIcon } from "@core/components/icons";
import { Segmented, Skeleton } from "@core/components/ui";
import { navigate } from "@core/router";
import { useLive } from "@core/live";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { Affiliation, Connection, Entity, EventRef, GraphPath, OrgRow, PersonLink, RelationshipView, TimelineEvent } from "./api";
import { AddRelationship } from "./forms";
import { Avatar, Card, EntityLink, StrengthDots } from "./bits";
import { formatDate, monthKey, relativeTime } from "./format";
import { TIER_META, TierBadge } from "./tier";

const NetworkCanvas = lazy(() => import("./NetworkCanvas")); // the graph library is large; load it only when a map is shown

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-1.5 text-ui">
      <dt className="text-ink-soft">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function Names({ people, max = 4 }: { people: { id: string; name: string }[]; max?: number }) {
  return (
    <span>
      {people.slice(0, max).map((p, i) => (
        <span key={p.id}>
          {i > 0 && ", "}
          <a href={`#/crm/e/${p.id}`} className="hover:underline">{p.name}</a>
        </span>
      ))}
      {people.length > max && <span className="text-ink-soft"> +{people.length - max}</span>}
    </span>
  );
}

function safeUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value) return null;
  try {
    const u = new URL(/^https?:\/\//i.test(value) ? value : `https://${value}`);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

export function AboutCard({ entity }: { entity: Entity }) {
  const a = entity.attributes as Record<string, string | undefined>;
  const aliases = (entity.attributes.aliases as string[] | undefined) ?? [];
  const links = [a.linkedin_url, a.website, a.url].map(safeUrl).filter(Boolean) as string[];
  if (!(entity.summary || a.email || a.phone || a.location || links.length || a.industry || a.description || aliases.length)) return null;
  const row = (icon: React.ReactNode, body: React.ReactNode) => (
    <div className="flex items-center gap-2 text-ui text-ink-soft [&_svg]:shrink-0">{icon}<span className="min-w-0 truncate text-ink">{body}</span></div>
  );
  return (
    <Card title="About">
      <div className="space-y-3">
        {entity.summary && <p className="whitespace-pre-wrap text-body leading-relaxed">{entity.summary}</p>}
        {a.description && <p className="text-label text-ink-soft">{a.description}</p>}
        <div className="grid gap-1.5 sm:grid-cols-2">
          {a.email && row(<MailIcon size={16} />, <a className="hover:underline" href={`mailto:${a.email}`}>{a.email}</a>)}
          {a.phone && row(<PhoneIcon size={16} />, <a className="hover:underline" href={`tel:${a.phone}`}>{a.phone}</a>)}
          {a.location && row(<MapPinIcon size={16} />, a.location)}
          {links.map((href) => row(<ExternalIcon key={href} size={16} />, <a key={href} className="hover:underline" href={href} target="_blank" rel="noreferrer noopener">{href.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}</a>))}
        </div>
        {aliases.length > 0 && <p className="text-hint text-ink-soft">Also known as {aliases.join(", ")}.</p>}
      </div>
    </Card>
  );
}

/** "You & Nancy": the tier, your rating, and the evidence behind it. */
export function ConnectionCard({ personId, name, connection: c }: { personId: string; name: string; connection: Connection }) {
  const { toast } = useShell();
  const rate = async (strength: number | null) => {
    try {
      await crmApi.setConnection(personId, strength);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const first = name.split(" ")[0];
  const met = c.meetings
    ? `${c.meetings} meeting${c.meetings === 1 ? "" : "s"}${c.first_met_at && c.meetings > 1 ? ` since ${formatDate(c.first_met_at, { day: undefined })}` : ""}`
    : null;
  return (
    <Card title={`You & ${first}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <TierBadge tier={c.tier} size="md" />
        <span className="text-hint text-ink-soft">{TIER_META[c.tier].blurb}</span>
      </div>
      <div className="inset-surface mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3.5 py-2.5 text-ui">
        <span className="text-ink-soft">Your rating</span>
        <StrengthDots value={c.strength ?? 0} onChange={(v) => void rate(v)} />
        <span className="text-ink-soft">{c.user_set ? "set by you" : c.strength ? "from your imports" : "not rated"}</span>
        {c.user_set && (
          <button className="ml-auto text-hint font-medium text-forest-deep hover:underline" onClick={() => void rate(null)}>
            Use automatic
          </button>
        )}
      </div>
      <dl className="mt-3">
        {c.roles.length > 0 && (
          <Fact label="How you know them">
            <div className="flex flex-wrap gap-1">{c.roles.map((r) => <span key={r} className="chip bg-surface-subtle text-ink-soft">{r}</span>)}</div>
          </Fact>
        )}
        {c.context && <Fact label="Context">{c.context}</Fact>}
        {met && <Fact label="Met together">{met}{c.last_met_at && <span className="text-ink-soft"> · last {relativeTime(c.last_met_at)}</span>}</Fact>}
        {c.coauthored > 0 && <Fact label="Wrote together">{c.coauthored} document{c.coauthored === 1 ? "" : "s"}</Fact>}
        {c.mentions > 0 && (
          <Fact label="Came up">
            {c.mentions}× in your meetings and documents
            {c.via.length > 0 && <> · via <Names people={c.via} max={3} /></>}
          </Fact>
        )}
        {c.mutual.length > 0 && <Fact label="Mutual contacts"><Names people={c.mutual} /></Fact>}
      </dl>
      {c.tier === "none" && <p className="mt-2 text-ui text-ink-soft">Nothing links {first} to you yet. Rate them above, or add a meeting.</p>}
    </Card>
  );
}

const years = (r: Affiliation["roles"][number]) => {
  const y = (d: string | null) => (d ? d.slice(0, 4) : null);
  return r.started_at || r.ended_at ? `${y(r.started_at) ?? "?"} – ${r.ended_at ? y(r.ended_at) : "now"}` : null;
};

export function AffiliationsCard({ affiliations }: { affiliations: Affiliation[] }) {
  const row = (a: Affiliation) => (
    <li key={a.org.id} className="flex items-start gap-3.5 px-5 py-3">
      <Avatar name={a.org.name} kind="organization" size={32} />
      <div className="min-w-0 flex-1">
        <EntityLink entity={a.org} />
        <div className="text-hint text-ink-soft">
          {a.roles.map((r, i) => (
            <span key={i}>
              {i > 0 && " · "}
              {r.kind === "works_at" ? r.title || (r.ended_at ? "Worked here" : "Works here") : [r.label, r.title].filter(Boolean).join(": ")}
              {years(r) && ` (${years(r)})`}
            </span>
          ))}
        </div>
      </div>
      {a.known > 0 && <a href={`#/crm/people?org=${a.org.id}`} className="shrink-0 text-hint text-ink-soft hover:underline">you know {a.known}</a>}
    </li>
  );
  const current = affiliations.filter((a) => a.current);
  const past = affiliations.filter((a) => !a.current);
  return (
    <Card title="Work and affiliations" flush>
      {affiliations.length === 0 ? (
        <p className="px-5 pb-4 text-ui text-ink-soft">No organizations yet.</p>
      ) : (
        <ul className="divide-y divide-line">
          {current.map(row)}
          {past.length > 0 && <li className="bg-surface-subtle/60 px-5 py-1.5 text-meta font-medium text-ink-soft">Previously</li>}
          {past.map(row)}
        </ul>
      )}
    </Card>
  );
}

const ROLE_LABEL: Record<string, string> = {
  attended: "attended", discussed: "came up", authored: "author", mentioned: "mentioned", "about them": "about them", "by their people": "by their people",
};

export function EventList({ events, empty, compact }: { events: EventRef[]; empty: string; compact?: boolean }) {
  if (!events.length) return <p className="px-5 pb-4 text-ui text-ink-soft">{empty}</p>;
  return (
    <ul className="divide-y divide-line">
      {events.map((ev) => {
        const others = ev.people.filter((p) => !p.is_self);
        return (
          <li key={ev.event.id}>
            <a href={`#/crm/e/${ev.event.id}`} className="flex gap-3.5 px-5 py-3 transition-colors duration-150 hover:bg-forest/[.05]">
              <span className="well">{ev.event.kind === "meeting" ? <CalendarIcon size={16} /> : <DocIcon size={16} />}</span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="text-label font-medium">{ev.event.name}</span>
                  <time className="shrink-0 text-meta text-ink-soft">{ev.event.occurred_at ? formatDate(ev.event.occurred_at) : "undated"}</time>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-meta text-ink-soft">
                  <span className="chip bg-surface-subtle text-ink-soft">{ROLE_LABEL[ev.role] ?? ev.role}</span>
                  {ev.with_me && <span className="chip bg-forest-soft text-forest-deep">with you</span>}
                  {others.length > 0 && <span className="truncate">{others.slice(0, 5).map((p) => p.name).join(", ")}{others.length > 5 && ` +${others.length - 5}`}</span>}
                </div>
                {!compact && ev.snippet && <p className="mt-1.5 line-clamp-2 text-ui text-ink-soft">{ev.snippet}</p>}
              </div>
            </a>
          </li>
        );
      })}
    </ul>
  );
}

export function PeopleList({ people, empty }: { people: PersonLink[]; empty: string }) {
  if (!people.length) return <p className="px-5 pb-4 text-ui text-ink-soft">{empty}</p>;
  return (
    <ul className="divide-y divide-line">
      {people.map((l) => (
        <li key={l.person.id + l.relation}>
          <a href={`#/crm/e/${l.person.id}`} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3.5 px-5 py-3 transition-colors duration-150 hover:bg-forest/[.05]">
            <Avatar name={l.person.name} size={32} />
            <div className="min-w-0">
              <div className="truncate text-label font-medium">{l.person.name}</div>
              <div className="truncate text-hint text-ink-soft">{[l.relation, l.detail ?? l.person.subtitle].filter(Boolean).join(" · ")}</div>
            </div>
            <TierBadge tier={l.tier} />
          </a>
        </li>
      ))}
    </ul>
  );
}

/** For an organization: who you know there, best first. */
export function WayInCard({ org }: { org: OrgRow }) {
  return (
    <Card title="Your way in" flush>
      {org.mine ? (
        <p className="px-5 pb-4 text-ui text-ink-soft">{org.mine === "current" ? "You work here." : "You used to work here."}</p>
      ) : org.contacts.length === 0 ? (
        <p className="px-5 pb-4 text-ui text-ink-soft">You don’t know anyone here yet. The paths below show who could introduce you.</p>
      ) : (
        <ul className="divide-y divide-line">
          {org.contacts.map((c) => (
            <li key={c.person.id}>
              <a href={`#/crm/e/${c.person.id}`} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3.5 px-5 py-3 hover:bg-forest/[.05]">
                <Avatar name={c.person.name} size={32} />
                <div className="min-w-0">
                  <div className="truncate text-label font-medium">{c.person.name}</div>
                  {c.person.subtitle && <div className="truncate text-hint text-ink-soft">{c.person.subtitle}</div>}
                </div>
                <TierBadge tier={c.tier} />
              </a>
            </li>
          ))}
        </ul>
      )}
      {org.known > org.contacts.length && (
        <a href={`#/crm/people?org=${org.org.id}`} className="block px-5 pb-4 pt-2 text-ui font-medium text-forest-deep hover:underline">
          All {org.known} people you know here
        </a>
      )}
    </Card>
  );
}

/** Chains like "You → Hannah Cole → Elena Petrova". Pass onPick to make them selectable. */
export function PathChains({ paths, activeIndex, onPick }: { paths: GraphPath[]; activeIndex?: number; onPick?: (i: number) => void }) {
  const { data: meta } = useLive(crmApi.meta);
  const rel = (kind: string, outgoing: boolean) => {
    const r = meta?.relationship_kinds[kind];
    return r ? (outgoing ? r.label : r.inverse) : kind;
  };
  return (
    <ol className="space-y-2.5">
      {paths.map((p, i) => (
        <li key={i}>
          <div
            role={onPick ? "button" : undefined}
            tabIndex={onPick ? 0 : undefined}
            onClick={() => onPick?.(i)}
            onKeyDown={(e) => e.key === "Enter" && onPick?.(i)}
            className={`inset-surface px-3.5 py-2.5 ${onPick ? "cursor-pointer hover:bg-forest/[.05]" : ""} ${activeIndex === i ? "ring-2 ring-forest/55" : ""}`}
          >
            <div className="flex flex-wrap items-center gap-x-1 gap-y-1 text-label">
              {p.nodes.map((n, j) => {
                const link = p.links[j - 1];
                return (
                  <span key={n.id} className="inline-flex items-center gap-1">
                    {j > 0 && (
                      <span className="inline-flex items-center text-meta text-ink-soft">
                        <ChevronRightIcon size={12} />{rel(link.kind, link.source === p.nodes[j - 1].id)}<ChevronRightIcon size={12} />
                      </span>
                    )}
                    <a href={`#/crm/e/${n.id}`} onClick={(e) => e.stopPropagation()} className="font-medium hover:underline">{n.is_self ? "You" : n.name}</a>
                  </span>
                );
              })}
            </div>
            <div className="mt-1 text-meta text-ink-soft">
              {p.hops} hop{p.hops === 1 ? "" : "s"} · tie strength {Math.round(p.score * 100)}%
              {p.hops > 1 && !p.nodes[1].is_self && p.nodes[1].kind === "person" && <> · ask {p.nodes[1].name.split(" ")[0]} for an intro</>}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** "How you're connected": shortest chains from you, strongest first. */
export function PathsCard({ entity }: { entity: Entity }) {
  const [peopleOnly, setPeopleOnly] = useState(true);
  const { data } = useLive(() => crmApi.paths({ target: entity.id, through: peopleOnly ? "person" : undefined }), [entity.id, peopleOnly]);
  return (
    <Card
      title="How you’re connected"
      action={
        <label className="flex items-center gap-1.5 text-hint text-ink-soft">
          <input type="checkbox" checked={peopleOnly} onChange={(e) => setPeopleOnly(e.target.checked)} className="accent-forest" /> via people only
        </label>
      }
    >
      {!data ? (
        <Skeleton className="h-12 w-full rounded-lg" />
      ) : data.paths.length === 0 ? (
        <p className="text-ui text-ink-soft">No path within 4 hops{peopleOnly ? " through people" : ""}.</p>
      ) : (
        <PathChains paths={data.paths.slice(0, 3)} />
      )}
    </Card>
  );
}

/** A small map of someone's neighborhood, with a way into the whole network. */
export function MiniNetwork({ entity }: { entity: Entity }) {
  const [depth, setDepth] = useState(1);
  const { data } = useLive(() => crmApi.graph({ center: entity.id, depth, max_nodes: 120 }), [entity.id, depth]);
  return (
    <Card
      title="Neighborhood"
      flush
      action={
        <div className="flex items-center gap-2">
          <Segmented size="sm" label="Hops" value={String(depth)} onChange={(v) => setDepth(Number(v))} options={[{ id: "1", label: "1 hop" }, { id: "2", label: "2 hops" }]} />
          <a className="btn btn-sm btn-ghost" href={`#/crm/network?focus=${entity.id}`}><NetworkIcon size={16} /> Open</a>
        </div>
      }
    >
      {data && data.nodes.length > 1 ? (
        <Suspense fallback={<Skeleton className="h-[300px] w-full" />}><NetworkCanvas graph={data} height={300} selectedId={entity.id} onNodeClick={(n) => n.id !== entity.id && navigate(`crm/e/${n.id}`)} labels={data.nodes.length <= 25 ? "all" : "auto"} /></Suspense>
      ) : (
        <p className="px-5 pb-4 text-ui text-ink-soft">{data ? "No connections yet." : "Loading…"}</p>
      )}
    </Card>
  );
}

export function AddNote({ entityId }: { entityId: string }) {
  const { toast } = useShell();
  const [body, setBody] = useState("");
  const add = async () => {
    try {
      await crmApi.addNote(entityId, body.trim());
      setBody("");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (body.trim()) void add(); }}>
      <textarea
        className="field min-h-10 flex-1 resize-y"
        rows={1}
        placeholder="Add a note. The first line becomes its title."
        aria-label="Add a note"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && body.trim()) void add(); }}
      />
      <button className="btn btn-md btn-primary" disabled={!body.trim()}><PlusIcon size={18} /> Add</button>
    </form>
  );
}

const TYPE_ICON: Record<TimelineEvent["type"], React.ReactNode> = {
  meeting: <CalendarIcon size={14} />, document: <DocIcon size={14} />, relationship: <ChevronRightIcon size={14} />, relationship_end: <CloseIcon size={14} />, note: <DocIcon size={14} />,
};

export function TimelineCard({ entityId }: { entityId: string }) {
  const { data } = useLive(() => crmApi.timeline(entityId), [entityId]);
  let last = "";
  const now = Date.now();
  return (
    <Card title="Timeline">
      <AddNote entityId={entityId} />
      {!data ? (
        <Skeleton className="mt-3 h-24 w-full rounded-lg" />
      ) : data.length === 0 ? (
        <p className="mt-3 text-ui text-ink-soft">Meetings, dated relationships and notes show up here.</p>
      ) : (
        <ol className="mt-2 max-h-[640px] overflow-y-auto pr-1">
          {data.map((ev) => {
            const month = monthKey(ev.at);
            const header = month !== last;
            last = month;
            return (
              <li key={ev.id} className="list-none">
                {header && <div className="sticky top-0 z-[1] bg-surface pb-1 pt-3 text-meta font-medium text-ink-soft">{month}</div>}
                <div className="flex gap-3 py-1.5">
                  <span className="well h-7 w-7 shrink-0 rounded-full">{TYPE_ICON[ev.type]}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-3">
                      <div className="min-w-0 text-ui">
                        {ev.entity && ev.type !== "note" ? <a href={`#/crm/e/${ev.entity.id}`} className="font-medium hover:underline">{ev.title}</a> : <span className="font-medium">{ev.title}</span>}
                        {new Date(ev.at).getTime() > now && <span className="ml-1.5 text-meta text-forest-deep">upcoming</span>}
                      </div>
                      <time className="shrink-0 text-meta tabular-nums text-ink-soft" dateTime={ev.at}>{formatDate(ev.at, { year: undefined })}</time>
                    </div>
                    {ev.detail && <p className={`mt-0.5 text-hint text-ink-soft ${ev.type === "note" ? "whitespace-pre-wrap" : ""}`}>{ev.type === "note" ? ev.detail.split("\n").slice(1).join("\n").trim() || null : ev.detail}</p>}
                    {ev.via && <p className="text-meta text-ink-soft">via <a href={`#/crm/e/${ev.via.id}`} className="hover:underline">{ev.via.name}</a></p>}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}

export function NotesCard({ entityId }: { entityId: string }) {
  const { toast, confirm } = useShell();
  const { data } = useLive(() => crmApi.notes(entityId), [entityId]);
  const remove = async (id: string) => {
    if (!(await confirm({ title: "Delete this note?", body: "It can’t be brought back.", confirmLabel: "Delete", tone: "danger" }))) return;
    try {
      await crmApi.deleteNote(id);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <Card title="Notes">
      <AddNote entityId={entityId} />
      <ul className="mt-3 space-y-3">
        {data?.map((n) => (
          <li key={n.id} className="inset-surface group p-3.5">
            <div className="mb-1 flex items-center justify-between text-meta text-ink-soft">
              <span>{formatDate(n.occurred_at)} · {n.source === "ingest" ? "original notes" : n.source}</span>
              <button className="icon-btn h-7 w-7 opacity-0 group-hover:opacity-100 focus:opacity-100" aria-label="Delete note" onClick={() => void remove(n.id)}><TrashIcon size={14} /></button>
            </div>
            <p className="max-h-80 overflow-y-auto whitespace-pre-wrap text-label">{n.body}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function RelationshipsCard({ entity, relationships }: { entity: Entity; relationships: RelationshipView[] }) {
  const { toast } = useShell();
  const [adding, setAdding] = useState(false);
  const groups = new Map<string, RelationshipView[]>();
  for (const r of relationships) groups.set(r.label, [...(groups.get(r.label) ?? []), r]);
  const sorted = [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <Card title={`Relationships (${relationships.length})`} action={<button className="btn btn-sm btn-ghost" onClick={() => setAdding((a) => !a)}><PlusIcon size={16} /> Add</button>}>
      {adding && <AddRelationship entity={entity} onDone={() => setAdding(false)} />}
      {sorted.length === 0 && !adding && <p className="text-ui text-ink-soft">No relationships yet.</p>}
      <div className="space-y-4">
        {sorted.map(([label, rels]) => (
          <div key={label}>
            <h3 className="mb-1 text-meta font-medium text-ink-soft">{label}</h3>
            <ul>
              {rels.map((r) => {
                const detail = [r.properties.title, r.properties.context, r.started_at && `since ${formatDate(r.started_at)}`, r.ended_at && `until ${formatDate(r.ended_at)}`].filter(Boolean).join(" · ");
                return (
                  <li key={r.id} className="group flex items-center gap-2 rounded-sm px-1.5 py-1.5 hover:bg-forest/[.05]">
                    <div className="min-w-0 flex-1 text-ui">
                      <EntityLink entity={r.other} />
                      {detail && <div className="truncate text-hint text-ink-soft">{detail}</div>}
                    </div>
                    <StrengthDots value={r.strength} onChange={(strength) => void act(() => crmApi.updateRelationship(r.id, { strength }))} />
                    <button className="icon-btn h-7 w-7 opacity-0 group-hover:opacity-100 focus:opacity-100" aria-label={`Remove ${label} ${r.other.name}`} onClick={() => void act(() => crmApi.deleteRelationship(r.id))}>
                      <CloseIcon size={14} />
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </Card>
  );
}
