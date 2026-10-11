import { useState } from "react";
import { CloseIcon, OrgIcon, PlusIcon, SearchIcon } from "@core/components/icons";
import { PageHeader, Segmented, Select, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { navigate, useQueryParams } from "@core/router";
import { crmApi } from "./api";
import { EntityFormDialog } from "./forms";
import type { OrgRow, OrgScope } from "./api";
import { Avatar, Empty, Tags, useDebounced } from "./bits";
import { relativeTime } from "./format";
import { TierBars } from "./tier";

const PAGE = 100;

const SCOPES: { id: OrgScope; label: string; blurb: string }[] = [
  { id: "known", label: "Where you know people", blurb: "Your own organizations, and ones where you know someone." },
  { id: "connected", label: "Anyone in your network", blurb: "Organizations with at least one person on file." },
  { id: "mentioned", label: "Only mentioned", blurb: "Named in meetings or documents, with nobody linked yet." },
  { id: "all", label: "All", blurb: "Every organization." },
];

const SORTS = [
  { value: "known", label: "People you know" },
  { value: "people", label: "Most people" },
  { value: "recent", label: "Recent activity" },
  { value: "name", label: "Name" },
];

function peopleLine(r: OrgRow): string {
  const parts: string[] = [];
  if (r.members) parts.push(`${r.members} ${r.members === 1 ? "person" : "people"}`);
  if (r.past) parts.push(`${r.past} former`);
  if (r.affiliates) parts.push(`${r.affiliates} advisor${r.affiliates === 1 ? "" : "s"} or other`);
  if (!parts.length && r.mentions) parts.push(`mentioned ${r.mentions}×`);
  return parts.join(" · ");
}

export function OrgLine({ row }: { row: OrgRow }) {
  return (
    <a
      href={`#/crm/e/${row.org.id}`}
      className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3.5 px-5 py-3 transition-colors duration-150 hover:bg-forest/[.05] sm:grid-cols-[auto_minmax(0,1fr)_minmax(0,14rem)_6.5rem]"
    >
      <Avatar name={row.org.name} kind="organization" />
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-label font-medium">{row.org.name}</span>
          {row.mine && <span className="chip bg-forest-soft text-forest-deep">{row.mine === "current" ? "your organization" : "your former organization"}</span>}
        </div>
        <div className="truncate text-hint text-ink-soft">{[peopleLine(row), row.org.subtitle].filter(Boolean).join(" · ") || " "}</div>
      </div>
      <div className="hidden min-w-0 text-ui sm:block">
        {row.contacts.length ? (
          <div className="flex min-w-0 items-center gap-1.5">
            <TierBars tier={row.best_tier} />
            <span className="truncate text-ink-soft">
              {row.contacts.map((c) => c.person.name).join(", ")}
              {row.known > row.contacts.length && ` +${row.known - row.contacts.length}`}
            </span>
          </div>
        ) : (
          <span className="text-ink-soft">No one you know yet</span>
        )}
      </div>
      <div className="text-right text-meta text-ink-soft">
        <div className="tabular-nums text-ink">{row.known ? `you know ${row.known}` : " "}</div>
        <div className="mt-0.5 flex justify-end gap-1">{row.last_activity_at ? relativeTime(row.last_activity_at) : <Tags tags={row.tags} max={1} />}</div>
      </div>
    </a>
  );
}

export default function Organizations() {
  const [params, setParams] = useQueryParams();
  const [creating, setCreating] = useState(false);
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const dq = useDebounced(q);
  const scope = (params.get("scope") as OrgScope | null) ?? "known";
  const sort = params.get("sort") ?? "known";
  const tag = params.get("tag") ?? undefined;

  const { data, error } = useLive(() => crmApi.organizations({ q: dq, scope, sort, tag, limit }), [dq, scope, sort, tag, limit]);
  const s = data?.scopes;
  const active = SCOPES.find((x) => x.id === scope)!;

  return (
    <>
      <PageHeader title="Organizations"
        actions={<button className="btn btn-md btn-primary" onClick={() => setCreating(true)}><PlusIcon size={18} /> New organization</button>} subtitle={s ? `You know people at ${s.known} of ${s.all}` : undefined} />
      <div className="animate-enter space-y-3" style={{ animationDelay: "60ms" }}>
        <div className="-mx-1 overflow-x-auto px-1 pb-1">
          <Segmented
            label="Which organizations"
            value={scope}
            onChange={(v) => { setLimit(PAGE); setParams({ scope: v === "known" ? null : v }); }}
            options={SCOPES.map((x) => ({ id: x.id, label: <>{x.label} {s && <span className="tabular-nums text-ink-soft">{s[x.id]}</span>}</> }))}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-52 max-w-sm flex-1">
            <SearchIcon size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
            <input className="field h-10 w-full pl-9" placeholder="Search organizations" aria-label="Search organizations" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <Select label="Sort by" value={sort} onChange={(v) => setParams({ sort: v === "known" ? null : v })} options={SORTS} />
          {tag && (
            <button className="chip bg-forest-soft text-forest-deep" onClick={() => setParams({ tag: null })} aria-label={`Remove the ${tag} filter`}>
              #{tag} <CloseIcon size={12} />
            </button>
          )}
        </div>
        <p className="text-hint text-ink-soft">{active.blurb}</p>

        {error && <p className="text-ui text-trail-deep">Couldn’t load organizations: {error}</p>}
        {!data && !error && <Skeleton className="h-64 w-full rounded-xl" />}
        {data && data.items.length === 0 && (
          <Empty icon={<OrgIcon size={20} />} title={dq || tag ? "No matches" : "Nothing here"}>
            {scope === "known" && !dq ? "Organizations appear here once you know someone who works there." : "Try a different search or scope."}
          </Empty>
        )}
        {data && data.items.length > 0 && (
          <div className="panel divide-y divide-line overflow-hidden">
            {data.items.map((row) => (
              <OrgLine key={row.org.id} row={row} />
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
      {creating && <EntityFormDialog kind="organization" onClose={() => setCreating(false)} onSaved={(e) => navigate(`crm/e/${e.id}`)} />}
    </>
  );
}
