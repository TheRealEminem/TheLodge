// One record's page: a person, organization, meeting, document or topic.
import { useState } from "react";
import type { ReactNode } from "react";
import { BackIcon, MergeIcon, NetworkIcon, PencilIcon, PersonIcon, TrashIcon } from "@core/components/icons";
import { Segmented, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import type { RouteProps } from "@core/registry";
import { navigate, useQueryParams } from "@core/router";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { Entity, EntityContext, PersonLink, RelationshipView } from "./api";
import { AboutCard, AffiliationsCard, ConnectionCard, EventList, MiniNetwork, NotesCard, PathsCard, PeopleList, RelationshipsCard, TimelineCard, WayInCard } from "./cards";
import { Avatar, Card, EntityLink, KIND_LABEL } from "./bits";
import { Briefing } from "./Briefing";
import { DuplicatesCard, MergedCard } from "./Duplicates";
import { EntityFormDialog, MergeDialog } from "./forms";
import { formatDate } from "./format";
import { PictureDialog } from "./PictureDialog";
import { ResearchCard } from "./Research";
import { TierBadge, connectionLine } from "./tier";

export default function Profile({ params }: RouteProps) {
  const { data, error } = useLive(() => crmApi.detail(params.id), [params.id]);
  const { data: ctx } = useLive(() => crmApi.context(params.id), [params.id]);
  if (error) return <Missing id={params.id} error={error} />;
  if (!data) return <Skeleton className="h-40 w-full rounded-xl" />;
  return <ProfileView entity={data.entity} relationships={data.relationships} ctx={ctx ?? undefined} />;
}

/** A record that's gone: if it was merged into another, that's where it lives now. */
function Missing({ id, error }: { id: string; error: string }) {
  const { data } = useLive(() => crmApi.movedTo(id), [id]);
  if (data?.id) {
    return (
      <p className="inset-surface px-5 py-4 text-ui text-ink-soft">
        This record was merged into another. <a className="font-medium text-forest-deep hover:underline" href={`#/crm/e/${data.id}`}>Go to it</a>
      </p>
    );
  }
  return <p className="text-ui text-trail-deep">{error}</p>;
}

function ProfileView({ entity, relationships, ctx }: { entity: Entity; relationships: RelationshipView[]; ctx?: EntityContext }) {
  return (
    <div>
      <Header entity={entity} ctx={ctx} />
      {entity.kind === "person" ? <PersonTabs entity={entity} relationships={relationships} ctx={ctx} />
        : entity.kind === "organization" ? <OrgTabs entity={entity} relationships={relationships} ctx={ctx} />
        : entity.kind === "topic" ? <TopicTabs entity={entity} relationships={relationships} ctx={ctx} />
        : <EventPage entity={entity} relationships={relationships} ctx={ctx} />}
    </div>
  );
}

// ── Header ────────────────────────────────────────────────────────────

function HeaderLine({ entity, ctx }: { entity: Entity; ctx?: EntityContext }) {
  if (entity.kind === "meeting" || entity.kind === "document") {
    return <>{entity.occurred_at ? formatDate(entity.occurred_at, { weekday: "short", hour: "numeric", minute: "2-digit" }) : "Undated"}</>;
  }
  if (entity.kind === "person" && ctx?.connection && !entity.is_self) {
    const line = connectionLine(ctx.connection);
    return <span className="inline-flex flex-wrap items-center gap-x-2.5"><TierBadge tier={ctx.connection.tier} />{line && <span>{line}</span>}</span>;
  }
  if (entity.kind === "organization" && ctx?.org) {
    const o = ctx.org;
    return (
      <span className="inline-flex flex-wrap items-center gap-x-2.5">
        {o.mine ? <span className="chip bg-forest-soft text-forest-deep">{o.mine === "current" ? "your organization" : "your former organization"}</span> : <TierBadge tier={o.best_tier} />}
        <span>{o.members} {o.members === 1 ? "person" : "people"}{o.known > 0 && ` · you know ${o.known}`}</span>
      </span>
    );
  }
  return <>{entity.degree} connection{entity.degree === 1 ? "" : "s"}</>;
}

function Header({ entity, ctx }: { entity: Entity; ctx?: EntityContext }) {
  const { toast, confirm } = useShell();
  const [editing, setEditing] = useState(false);
  const [picturing, setPicturing] = useState(false);
  const [merging, setMerging] = useState(false);
  const label = KIND_LABEL[entity.kind];

  const remove = async () => {
    if (!(await confirm({ title: `Delete ${entity.name}?`, body: "Its relationships and notes are deleted too. This can’t be undone.", confirmLabel: "Delete", tone: "danger" }))) return;
    try {
      await crmApi.deleteEntity(entity.id);
      navigate(entity.kind === "organization" ? "crm/organizations" : entity.kind === "person" ? "crm/people" : "crm/people");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const makeMe = async () => {
    try {
      await crmApi.makeMe(entity.id);
      toast(`${entity.name} is now you`);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <header className="mb-6 animate-enter">
      <a href={`#/${entity.kind === "organization" ? "crm/organizations" : "crm/people"}`} className="btn btn-sm btn-ghost -ml-2 mb-3">
        <BackIcon size={16} /> {entity.kind === "organization" ? "Organizations" : "People"}
      </a>
      <div className="flex flex-wrap items-start gap-4">
        <button className="group relative shrink-0 rounded-full" aria-label="Change the picture" data-tip="Add or change the picture" onClick={() => setPicturing(true)}>
          <Avatar id={entity.id} name={entity.name} kind={entity.kind} size={56} />
          <span className="absolute inset-0 grid place-items-center rounded-full bg-[var(--scrim)] text-surface opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"><PencilIcon size={16} /></span>
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="page-title">{entity.name}</h1>
            {entity.is_self && <span className="chip bg-forest-soft text-forest-deep">you</span>}
            <span className="chip bg-surface-subtle text-ink-soft">{label.one}</span>
          </div>
          {entity.subtitle && <p className="mt-1 text-body text-ink-soft">{entity.subtitle}</p>}
          <div className="mt-1.5 text-hint text-ink-soft"><HeaderLine entity={entity} ctx={ctx} /></div>
          {entity.tags.length > 0 && (
            <div className="mt-2.5 flex flex-wrap gap-1">
              {entity.tags.map((t) => (
                <a key={t} href={`#/${entity.kind === "organization" ? "crm/organizations" : "crm/people"}?tag=${encodeURIComponent(t)}`} className="chip bg-surface-subtle text-ink-soft hover:bg-forest/10">#{t}</a>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <a className="btn btn-sm btn-soft" href={`#/crm/network?focus=${entity.id}`}><NetworkIcon size={16} /> Network</a>
        <button className="btn btn-sm btn-soft" onClick={() => setEditing(true)}><PencilIcon size={16} /> Edit</button>
        {entity.kind === "person" && !entity.is_self && <button className="btn btn-sm btn-ghost" onClick={() => void makeMe()}><PersonIcon size={16} /> This is me</button>}
        <button className="btn btn-sm btn-ghost" data-tip="Merge a duplicate into another record" onClick={() => setMerging(true)}><MergeIcon size={16} /> Merge</button>
        <button className="btn btn-sm btn-danger-ghost" aria-label="Delete" onClick={() => void remove()}><TrashIcon size={16} /></button>
      </div>
      {picturing && <PictureDialog entity={entity} onClose={() => setPicturing(false)} />}
      {editing && <EntityFormDialog kind={entity.kind} entity={entity} onClose={() => setEditing(false)} />}
      {merging && <MergeDialog entity={entity} onClose={() => setMerging(false)} onMerged={(kept) => navigate(`crm/e/${kept.id}`)} />}
    </header>
  );
}

// ── Tabs ──────────────────────────────────────────────────────────────

interface TabDef { id: string; label: string; count?: number }

function useTab(fallback: string): [string, (t: string) => void] {
  const [params, setParams] = useQueryParams();
  return [params.get("tab") ?? fallback, (t) => setParams({ tab: t === fallback ? null : t })];
}

function Tabs({ tabs, active, onChange }: { tabs: TabDef[]; active: string; onChange: (t: string) => void }) {
  return (
    <div className="-mx-1 mb-5 overflow-x-auto px-1 pb-1">
      <Segmented
        kind="tab"
        label="Sections"
        value={active}
        onChange={onChange}
        options={tabs.map((t) => ({ id: t.id, label: <>{t.label} {t.count !== undefined && <span className="tabular-nums text-ink-soft">{t.count}</span>}</> }))}
      />
    </div>
  );
}

const Stack = ({ children }: { children: ReactNode }) => <div className="grid gap-5">{children}</div>;
const Loading = () => <Skeleton className="h-40 w-full rounded-xl" />;

function HistoryTab({ entity, relationships }: { entity: Entity; relationships: RelationshipView[] }) {
  return (
    <Stack>
      <TimelineCard entityId={entity.id} />
      <RelationshipsCard entity={entity} relationships={relationships} />
    </Stack>
  );
}

const flush = (title: string, body: ReactNode, action?: ReactNode) => <Card title={title} flush action={action}>{body}</Card>;

function PersonTabs({ entity, relationships, ctx }: { entity: Entity; relationships: RelationshipView[]; ctx?: EntityContext }) {
  const [tab, setTab] = useTab("overview");
  const known = ctx?.people.filter((l) => ["strong", "working", "light"].includes(l.tier)) ?? [];
  const others = ctx?.people.filter((l) => !["strong", "working", "light"].includes(l.tier)) ?? [];
  const tabs: TabDef[] = [
    { id: "overview", label: "Overview" },
    { id: "meetings", label: "Meetings", count: ctx?.meetings.length },
    { id: "documents", label: "Documents", count: ctx?.documents.length },
    { id: "people", label: "People", count: ctx?.people.length },
    { id: "history", label: "Notes and history" },
  ];
  return (
    <>
      <Tabs tabs={tabs} active={tab} onChange={setTab} />
      {!ctx ? <Loading /> : tab === "overview" ? (
        <Stack>
          <DuplicatesCard entity={entity} />
          <MergedCard entity={entity} />
          {!entity.is_self && <Briefing person={entity} />}
          {!entity.is_self && <ResearchCard person={entity} />}
          {!entity.is_self && ctx.connection && <ConnectionCard personId={entity.id} name={entity.name} connection={ctx.connection} />}
          <AboutCard entity={entity} />
          <AffiliationsCard affiliations={ctx.affiliations} />
          {flush("Recent meetings", <EventList events={ctx.meetings.slice(0, 3)} compact empty="No meetings with or about them yet." />,
            ctx.meetings.length > 3 && <button className="btn btn-sm btn-ghost" onClick={() => setTab("meetings")}>All {ctx.meetings.length}</button>)}
          {!entity.is_self && ctx.connection && ["indirect", "none"].includes(ctx.connection.tier) && <PathsCard entity={entity} />}
          <MiniNetwork entity={entity} />
        </Stack>
      ) : tab === "meetings" ? flush("Meetings", <EventList events={ctx.meetings} empty="No meetings with or about them yet." />)
        : tab === "documents" ? flush("Documents", <EventList events={ctx.documents} empty="No documents by or about them yet." />)
        : tab === "people" ? (
          <Stack>
            {flush(`People you both know (${known.length})`, <PeopleList people={known} empty="No one in common yet." />)}
            {flush(`Others in their network (${others.length})`, <PeopleList people={others} empty="No one else yet." />)}
          </Stack>
        ) : <HistoryTab entity={entity} relationships={relationships} />}
    </>
  );
}

function OrgTabs({ entity, relationships, ctx }: { entity: Entity; relationships: RelationshipView[]; ctx?: EntityContext }) {
  const [tab, setTab] = useTab("overview");
  const people = ctx?.people ?? [];
  const groups: [string, PersonLink[]][] = [
    ["Works here", people.filter((l) => l.current && l.relation === "works at")],
    ["Advisors, investors and others", people.filter((l) => l.current && l.relation !== "works at")],
    ["Previously", people.filter((l) => !l.current)],
  ];
  const events = (ctx?.meetings.length ?? 0) + (ctx?.documents.length ?? 0);
  const tabs: TabDef[] = [
    { id: "overview", label: "Overview" },
    { id: "people", label: "People", count: ctx?.people.length },
    { id: "meetings", label: "Meetings and documents", count: ctx ? events : undefined },
    { id: "history", label: "Notes and history" },
  ];
  const latest = ctx ? [...ctx.meetings, ...ctx.documents].sort((a, b) => (b.event.occurred_at ?? "").localeCompare(a.event.occurred_at ?? "")).slice(0, 3) : [];
  return (
    <>
      <Tabs tabs={tabs} active={tab} onChange={setTab} />
      {!ctx ? <Loading /> : tab === "overview" ? (
        <Stack>
          <DuplicatesCard entity={entity} />
          <MergedCard entity={entity} />
          {ctx.org && <WayInCard org={ctx.org} />}
          <AboutCard entity={entity} />
          {flush("People", <PeopleList people={people.slice(0, 8)} empty="No people linked yet." />,
            people.length > 8 && <button className="btn btn-sm btn-ghost" onClick={() => setTab("people")}>All {people.length}</button>)}
          {flush("Latest", <EventList events={latest} compact empty="No meetings or documents yet." />)}
          {ctx.orgs.length > 0 && (
            <Card title="Related organizations">
              <ul className="space-y-1.5 text-ui">
                {ctx.orgs.map((o) => (
                  <li key={o.org.id + o.relation} className="flex items-center justify-between gap-2">
                    <EntityLink entity={o.org} />
                    <span className="shrink-0 text-hint text-ink-soft">{o.relation}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {ctx.org && !ctx.org.mine && ctx.org.known === 0 && <PathsCard entity={entity} />}
          <MiniNetwork entity={entity} />
        </Stack>
      ) : tab === "people" ? (
        <Stack>
          {groups.filter(([, l]) => l.length).map(([label, list]) => flush(`${label} (${list.length})`, <PeopleList key={label} people={list} empty="" />))}
          {people.length === 0 && <p className="inset-surface px-5 py-8 text-center text-ui text-ink-soft">No people linked yet.</p>}
        </Stack>
      ) : tab === "meetings" ? (
        <Stack>
          {flush(`Meetings (${ctx.meetings.length})`, <EventList events={ctx.meetings} empty="No meetings yet." />)}
          {flush(`Documents (${ctx.documents.length})`, <EventList events={ctx.documents} empty="No documents yet." />)}
        </Stack>
      ) : <HistoryTab entity={entity} relationships={relationships} />}
    </>
  );
}

function TopicTabs({ entity, relationships, ctx }: { entity: Entity; relationships: RelationshipView[]; ctx?: EntityContext }) {
  const [tab, setTab] = useTab("overview");
  return (
    <>
      <Tabs tabs={[{ id: "overview", label: "Overview" }, { id: "history", label: "Notes and history" }]} active={tab} onChange={setTab} />
      {tab === "history" ? <HistoryTab entity={entity} relationships={relationships} /> : !ctx ? <Loading /> : (
        <Stack>
          <AboutCard entity={entity} />
          {flush(`People (${ctx.people.length})`, <PeopleList people={ctx.people} empty="No people linked yet." />)}
          {flush(`Meetings (${ctx.meetings.length})`, <EventList events={ctx.meetings} empty="Not discussed in any meeting yet." />)}
          {flush(`Documents (${ctx.documents.length})`, <EventList events={ctx.documents} empty="Not in any document yet." />)}
        </Stack>
      )}
    </>
  );
}

// ── Meetings and documents ────────────────────────────────────────────

function PeopleWithTier({ people, empty }: { people: PersonLink[]; empty: string }) {
  if (!people.length) return <p className="text-ui text-ink-soft">{empty}</p>;
  return (
    <ul className="space-y-2 text-ui">
      {people.map((l) => (
        <li key={l.person.id} className="flex items-center justify-between gap-2">
          <EntityLink entity={l.person} showSubtitle />
          {!l.person.is_self && <TierBadge tier={l.tier} />}
        </li>
      ))}
    </ul>
  );
}

function EventPage({ entity, relationships, ctx }: { entity: Entity; relationships: RelationshipView[]; ctx?: EntityContext }) {
  const actions = (entity.attributes.action_items as string[] | undefined) ?? [];
  const points = (entity.attributes.key_points as string[] | undefined) ?? [];
  const sourceFile = entity.attributes.source_file as string | undefined;
  const present = ctx?.people.filter((l) => ["attended", "authored", "subject"].includes(l.relation)) ?? [];
  const named = ctx?.people.filter((l) => ["discussed", "mentioned"].includes(l.relation)) ?? [];
  const bullets = (items: string[]) => (
    <ul className="space-y-1.5">
      {items.map((a, i) => <li key={i} className="flex gap-2.5 text-label"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-forest/50" />{a}</li>)}
    </ul>
  );
  return (
    <Stack>
      <Card title="Summary" action={sourceFile && <span className="truncate text-meta text-ink-soft">from {sourceFile}</span>}>
        {entity.summary ? <p className="whitespace-pre-wrap text-body leading-relaxed">{entity.summary}</p> : <p className="text-ui text-ink-soft">No summary.</p>}
        {points.length > 0 && <div className="mt-4"><h3 className="mb-1.5 text-ui font-semibold">Key points</h3>{bullets(points)}</div>}
        {actions.length > 0 && <div className="mt-4"><h3 className="mb-1.5 text-ui font-semibold">Action items</h3>{bullets(actions)}</div>}
      </Card>
      <div className="grid gap-5 sm:grid-cols-2">
        <Card title={entity.kind === "meeting" ? `Attendees (${present.length})` : `Authors and subject (${present.length})`}>
          <PeopleWithTier people={present} empty="None recorded." />
        </Card>
        <Card title={`${entity.kind === "meeting" ? "People who came up" : "People mentioned"} (${named.length})`}>
          <PeopleWithTier people={named} empty="No one else mentioned." />
        </Card>
      </div>
      {ctx && (ctx.orgs.length > 0 || ctx.topics.length > 0) && (
        <Card title="Organizations and topics">
          <div className="flex flex-wrap gap-x-5 gap-y-1.5 text-ui">
            {ctx.orgs.map((o) => <EntityLink key={o.org.id} entity={o.org} />)}
            {ctx.topics.map((t) => <EntityLink key={t.id} entity={t} />)}
          </div>
        </Card>
      )}
      <AboutCard entity={entity} />
      <NotesCard entityId={entity.id} />
      <RelationshipsCard entity={entity} relationships={relationships} />
    </Stack>
  );
}
