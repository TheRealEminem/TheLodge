// Groups: organizations, topics and tags are all named sets of people. Switch any of them on in the Network.
import { useMemo, useState } from "react";
import { NetworkIcon, SearchIcon } from "@core/components/icons";
import { PageHeader, Segmented, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { crmApi } from "./api";
import type { GroupKind } from "./api";
import { Empty } from "./bits";
import { GROUP_META, GROUP_ORDER, GroupGlyph } from "./groups";

export default function Groups() {
  const [kind, setKind] = useState<GroupKind | "all">("all");
  const [q, setQ] = useState("");
  const { data: net, error } = useLive(() => crmApi.network({ max_nodes: 10 }), []);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (net?.groups ?? []).filter((g) => (kind === "all" || g.kind === kind) && (!needle || g.name.toLowerCase().includes(needle)));
  }, [net?.groups, kind, q]);
  const count = (k: GroupKind) => net?.groups.filter((g) => g.kind === k).length ?? 0;
  return (
    <>
      <PageHeader title="Groups" subtitle="Organizations, topics and tags are all groups of people. Switch any of them on in the Network to pull their people together." />
      <div className="animate-enter space-y-3" style={{ animationDelay: "60ms" }}>
        <div className="flex flex-wrap items-center gap-3">
          <div className="-mx-1 overflow-x-auto px-1 pb-1">
            <Segmented
              kind="tab"
              label="Kind"
              value={kind}
              onChange={setKind}
              options={[{ id: "all", label: "All" }, ...GROUP_ORDER.map((k) => ({ id: k, label: `${GROUP_META[k].many} ${count(k)}` }))]}
            />
          </div>
          <div className="relative ml-auto w-full sm:w-64">
            <SearchIcon size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
            <input className="field h-9 w-full pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a group" aria-label="Find a group" />
          </div>
        </div>
        {error && <p className="text-ui text-trail-deep">{error}</p>}
        {!net && !error && <Skeleton className="h-64 w-full rounded-xl" />}
        {net && rows.length === 0 && <Empty icon={<NetworkIcon size={20} />} title="No groups here">A group needs at least two people: a shared employer, a topic they took part in, or a tag you give them.</Empty>}
        {rows.length > 0 && (
          <ul className="panel divide-y divide-line">
            {rows.map((g) => (
              <li key={g.id} className="flex items-center gap-3 px-5 py-3">
                <span className="well well-forest"><GroupGlyph kind={g.kind} size={16} /></span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-label font-medium">{g.name}</div>
                  <div className="text-meta text-ink-soft">{GROUP_META[g.kind].one} · {g.size} people</div>
                </div>
                {g.ref && <a className="btn btn-sm btn-ghost" href={`#/crm/e/${g.ref}`}>Open record</a>}
                <a className="btn btn-sm btn-soft" href={`#/crm/network?wells=${encodeURIComponent(g.id)}`}><NetworkIcon size={16} /> In the network</a>
              </li>
            ))}
          </ul>
        )}
        <p className="pt-2 text-hint text-ink-soft">
          The records underneath: <a className="underline" href="#/crm/organizations">organizations</a>, <a className="underline" href="#/crm/meetings">meetings and documents</a>, <a className="underline" href="#/crm/topics">topics</a>.
        </p>
      </div>
    </>
  );
}
