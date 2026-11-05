import { useState } from "react";
import { CloseIcon, PlusIcon, SearchIcon, UsersIcon } from "@core/components/icons";
import { PageHeader, Segmented, Select, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { keepFilters, navigate, useQueryLimit, useQueryParams, useQueryText } from "@core/router";
import { useMemo } from "react";
import { crmApi } from "./api";
import { EntityFormDialog } from "./forms";
import type { PersonRow, Tier } from "./api";
import { Avatar, Empty, Tags, roleLine, useDebounced } from "./bits";
import { FacetPicker, PutInHat } from "./hats";
import { NEEDS_RESEARCH_CHIP } from "./Research";
import { TIERS, TIER_META, TierBadge, TierBars, connectionLine } from "./tier";

const PAGE = 100;

const GROUPINGS = [
  { value: "", label: "No grouping" },
  { value: "org", label: "Group by organization" },
  { value: "tag", label: "Group by tag" },
];

const SORTS = [
  { value: "strength", label: "Connection strength" },
  { value: "recent", label: "Recent contact" },
  { value: "meetings", label: "Most meetings" },
  { value: "name", label: "Name" },
  { value: "added", label: "Recently added" },
];

export function TierFilter({ value, counts, onChange }: { value: Tier | "all"; counts?: Partial<Record<Tier, number>>; onChange: (t: Tier | "all") => void }) {
  const total = counts ? Object.values(counts).reduce((a, b) => a + (b ?? 0), 0) : undefined;
  const n = (c?: number) => (c === undefined ? null : <span className="tabular-nums text-ink-soft">{c}</span>);
  return (
    <div className="-mx-1 overflow-x-auto px-1 pb-1">
      <Segmented
        label="Connection tier"
        value={value}
        onChange={onChange}
        options={[
          { id: "all" as const, label: <>All {n(total)}</> },
          ...TIERS.map((t) => ({
            id: t as Tier | "all",
            label: (
              <span className="inline-flex items-center gap-1.5">
                <TierBars tier={t} />
                {TIER_META[t].label} {n(counts?.[t] ?? 0)}
              </span>
            ),
          })),
        ]}
      />
    </div>
  );
}

export function PersonLine({ row, showFlag = true }: { row: PersonRow; showFlag?: boolean }) {
  const c = row.connection;
  const sub = roleLine(row.title, row.org?.name) || row.location || "";
  return (
    <a
      href={`#/crm/e/${row.person.id}`}
      className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3.5 px-5 py-3 transition-colors duration-150 hover:bg-forest/[.05] sm:grid-cols-[auto_minmax(0,1fr)_7rem_minmax(0,13rem)]"
    >
      <Avatar id={row.person.id} name={row.person.name} />
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-label font-medium">{row.person.name}</span>
          {showFlag && row.needs_research && (
            <>
              <span className={`${NEEDS_RESEARCH_CHIP} hidden shrink-0 sm:inline-flex`}>needs research</span>
              <span className="h-2 w-2 shrink-0 rounded-full bg-sun sm:hidden" role="img" aria-label="Needs research" />
            </>
          )}
        </div>
        <div className="truncate text-hint text-ink-soft">{sub || " "}</div>
      </div>
      <TierBadge tier={c.tier} />
      <div className="hidden min-w-0 text-right text-meta text-ink-soft sm:block">
        <div className="truncate">{connectionLine(c) || " "}</div>
        <div className="mt-0.5 flex justify-end gap-1">
          <Tags tags={row.tags} />
        </div>
      </div>
    </a>
  );
}

keepFilters("crm/people");

export default function People() {
  const [params, setParams] = useQueryParams();
  const [creating, setCreating] = useState(false);
  const [q, setQ] = useQueryText();  // Home's finder links here with what was typed
  const [limit, setLimit] = useQueryLimit(PAGE);
  const dq = useDebounced(q);
  const tier = (params.get("tier") as Tier | null) ?? "all";
  const sort = params.get("sort") ?? "strength";
  const tag = params.get("tag") ?? undefined;
  const org = params.get("org") ?? undefined;
  const topic = params.get("topic") ?? undefined;
  const mtag = params.get("mtag") ?? undefined;
  const research = params.get("research") === "needed";
  const hat = params.get("nohat") ? "none" : "active";
  const groupBy = params.get("group") ?? "";
  const filters = { q: dq, tier: tier === "all" ? undefined : tier, tag, org, topic, mtag, hat };

  const { data, error } = useLive(
    () => crmApi.people({ ...filters, sort, limit: groupBy ? 1000 : limit, needs_research: research ? "true" : undefined }),
    [dq, tier, sort, tag, org, topic, mtag, hat, limit, research, groupBy],
  );
  const { data: facets } = useLive(() => crmApi.peopleFacets({ hat, tag, org, topic, mtag }), [hat, tag, org, topic, mtag]);
  const { data: checks } = useLive(crmApi.linkChecks);
  const c = data?.tiers;
  const filtered = Boolean(dq || tier !== "all" || tag || org || topic || mtag || research || params.get("nohat"));
  const set = (key: string) => (v: string | null) => { setLimit(PAGE); setParams({ [key]: v }); };
  const sections = useMemo(() => {
    if (!groupBy || !data) return [];
    const by = new Map<string, PersonRow[]>();
    const put = (name: string, row: PersonRow) => by.set(name, [...(by.get(name) ?? []), row]);
    for (const row of data.items) {
      if (groupBy === "org") put(row.org?.name ?? "No organization", row);
      else if (row.tags.length) row.tags.forEach((t) => put(`#${t}`, row));
      else put("No tag", row);
    }
    const last = (n: string) => n.startsWith("No ");
    return [...by.entries()].sort((a, b) => Number(last(a[0])) - Number(last(b[0])) || b[1].length - a[1].length || a[0].localeCompare(b[0]));
  }, [groupBy, data]);

  return (
    <>
      <PageHeader
        title="People"
        actions={<button className="btn btn-md btn-primary" onClick={() => setCreating(true)}><PlusIcon size={18} /> New person</button>}
        subtitle={c ? `${c.strong ?? 0} strong · ${c.working ?? 0} working · ${c.light ?? 0} light · ${c.indirect ?? 0} indirect` : undefined}
      />
      <div className="animate-enter space-y-3" style={{ animationDelay: "60ms" }}>
        <TierFilter value={tier} counts={c} onChange={(t) => { setLimit(PAGE); setParams({ tier: t === "all" ? null : t }); }} />
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-52 max-w-sm flex-1">
            <SearchIcon size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
            <input className="field h-10 w-full pl-9" placeholder="Name, role, organization or tag" aria-label="Search people" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <Select label="Sort by" value={sort} onChange={(v) => setParams({ sort: v === "strength" ? null : v })} options={SORTS} />
          <Select label="Group" value={groupBy} onChange={(v) => setParams({ group: v || null })} options={GROUPINGS} />
          {(research || (data?.needs_research ?? 0) > 0) && (
            <button
              className={research ? "chip bg-forest-soft text-forest-deep" : "chip bg-surface-subtle text-ink-soft hover:bg-forest/10"}
              aria-pressed={research}
              onClick={() => { setLimit(PAGE); setParams({ research: research ? null : "needed" }); }}
            >
              Needs research <span className="tabular-nums">{data?.needs_research ?? 0}</span>
              {research && <CloseIcon size={12} />}
            </button>
          )}
          {!!checks?.total && <a className="chip bg-surface-subtle text-ink-soft hover:bg-forest/10" href="#/crm/checks">Links to check <span className="tabular-nums">{checks.total}</span></a>}
        </div>
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter by">
          <FacetPicker label="Tag" value={tag} options={facets?.tags} onChange={set("tag")} />
          <FacetPicker label="Organization" value={org} options={facets?.orgs} onChange={set("org")} />
          <FacetPicker label="Topic" value={topic} options={facets?.topics} onChange={set("topic")} />
          <FacetPicker label="Meeting tag" value={mtag} options={facets?.meeting_tags} onChange={set("mtag")} />
          {params.get("nohat") && (
            <button className="chip h-9 bg-forest-soft px-3 text-forest-deep" onClick={() => setParams({ nohat: null })} aria-label="Remove the no-hat filter">
              In no hat yet <CloseIcon size={12} />
            </button>
          )}
          {filtered && <span className="ml-auto"><PutInHat count={data?.total ?? 0} ids={async () => (await crmApi.people({ ...filters, limit: 1000, needs_research: research ? "true" : undefined })).items.map((r) => r.person.id)} /></span>}
        </div>
        {tier !== "all" && <p className="text-hint text-ink-soft">{TIER_META[tier].blurb}.</p>}

        {error && <p className="text-ui text-trail-deep">Couldn’t load people: {error}</p>}
        {!data && !error && <Skeleton className="h-64 w-full rounded-xl" />}
        {data && data.items.length === 0 && (
          <Empty icon={<UsersIcon size={20} />} title={filtered ? "No one matches" : "No people yet"}>
            {filtered ? "Try a different search or filter." : "People appear here as you add them or import notes."}
          </Empty>
        )}
        {groupBy && sections.map(([name, rows]) => (
          <section key={name} className="space-y-1.5">
            <h2 className="flex items-baseline gap-2 px-1 pt-2 text-ui font-semibold">{name} <span className="font-normal tabular-nums text-ink-soft">{rows.length}</span></h2>
            <div className="panel divide-y divide-line overflow-hidden">
              {rows.map((row) => <PersonLine key={row.person.id} row={row} showFlag={!research} />)}
            </div>
          </section>
        ))}
        {!groupBy && data && data.items.length > 0 && (
          <div className="panel divide-y divide-line overflow-hidden">
            {data.items.map((row) => (
              <PersonLine key={row.person.id} row={row} showFlag={!research} />
            ))}
            {data.items.length < data.total && (
              <div className="p-2 text-center">
                <button className="btn btn-sm btn-ghost" onClick={() => setLimit((l) => l + PAGE)}>
                  Show more ({data.total - data.items.length} left)
                </button>
              </div>
            )}
          </div>
        )}
      </div>
      {creating && <EntityFormDialog kind="person" onClose={() => setCreating(false)} onSaved={(e) => navigate(`crm/e/${e.id}`)} />}
    </>
  );
}
