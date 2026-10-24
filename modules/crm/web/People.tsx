import { useState } from "react";
import { CloseIcon, PlusIcon, SearchIcon, UsersIcon } from "@core/components/icons";
import { PageHeader, Segmented, Select, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { navigate, useQueryParams } from "@core/router";
import { crmApi } from "./api";
import { EntityFormDialog } from "./forms";
import type { PersonRow, Tier } from "./api";
import { Avatar, Empty, Tags, roleLine, useDebounced } from "./bits";
import { NEEDS_RESEARCH_CHIP } from "./Research";
import { TIERS, TIER_META, TierBadge, TierBars, connectionLine } from "./tier";

const PAGE = 100;

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

export default function People() {
  const [params, setParams] = useQueryParams();
  const [creating, setCreating] = useState(false);
  const [q, setQ] = useState(() => params.get("q") ?? "");  // Home's finder links here with what was typed
  const [limit, setLimit] = useState(PAGE);
  const dq = useDebounced(q);
  const tier = (params.get("tier") as Tier | null) ?? "all";
  const sort = params.get("sort") ?? "strength";
  const tag = params.get("tag") ?? undefined;
  const org = params.get("org") ?? undefined;
  const research = params.get("research") === "needed";

  const { data, error } = useLive(
    () => crmApi.people({ q: dq, tier: tier === "all" ? undefined : tier, sort, tag, org, limit, needs_research: research ? "true" : undefined }),
    [dq, tier, sort, tag, org, limit, research],
  );
  const { data: orgEntity } = useLive(() => (org ? crmApi.entity(org) : Promise.resolve(null)), [org]);
  const c = data?.tiers;

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
          {org && (
            <button className="chip bg-forest-soft text-forest-deep" onClick={() => setParams({ org: null })} aria-label="Remove the organization filter">
              at {orgEntity?.entity.name ?? "…"} <CloseIcon size={12} />
            </button>
          )}
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
          {tag && (
            <button className="chip bg-forest-soft text-forest-deep" onClick={() => setParams({ tag: null })} aria-label={`Remove the ${tag} filter`}>
              #{tag} <CloseIcon size={12} />
            </button>
          )}
        </div>
        {tier !== "all" && <p className="text-hint text-ink-soft">{TIER_META[tier].blurb}.</p>}

        {error && <p className="text-ui text-trail-deep">Couldn’t load people: {error}</p>}
        {!data && !error && <Skeleton className="h-64 w-full rounded-xl" />}
        {data && data.items.length === 0 && (
          <Empty icon={<UsersIcon size={20} />} title={dq || tier !== "all" || tag || org || research ? "No one matches" : "No people yet"}>
            {dq || tier !== "all" || tag || org || research ? "Try a different search or filter." : "People appear here as you add them or import notes."}
          </Empty>
        )}
        {data && data.items.length > 0 && (
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
