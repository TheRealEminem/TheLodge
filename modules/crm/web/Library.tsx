// Meetings, documents and topics: the records behind your relationships.
import { useState } from "react";
import { CalendarIcon, DocIcon, PlusIcon, SearchIcon, TopicIcon } from "@core/components/icons";
import { PageHeader, Segmented, Select, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import type { RouteProps } from "@core/registry";
import { navigate } from "@core/router";
import { crmApi } from "./api";
import type { EntityKind } from "./api";
import { Empty, KIND_LABEL, Tags, useDebounced } from "./bits";
import { EntityFormDialog } from "./forms";
import { formatDate } from "./format";

const KINDS: EntityKind[] = ["meeting", "document", "topic"];
const ICON = { meeting: <CalendarIcon size={20} />, document: <DocIcon size={20} />, topic: <TopicIcon size={20} /> } as Record<string, JSX.Element>;
const SORTS: Record<string, { value: string; label: string }[]> = {
  meeting: [{ value: "occurred", label: "Date" }, { value: "name", label: "Name" }],
  document: [{ value: "occurred", label: "Date" }, { value: "name", label: "Name" }],
  topic: [{ value: "connections", label: "Most connected" }, { value: "name", label: "Name" }],
};

export default function Library({ params }: RouteProps & { params: { kind?: string } }) {
  const kind = (KINDS.find((k) => k === params.kind) ?? "meeting") as EntityKind;
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [sort, setSort] = useState(SORTS[kind][0].value);
  const [limit, setLimit] = useState(100);
  const [creating, setCreating] = useState(false);
  const { data } = useLive(() => crmApi.entities({ kind, q: dq || undefined, sort, limit }), [kind, dq, sort, limit]);
  const label = KIND_LABEL[kind];
  return (
    <>
      <PageHeader
        title="Meetings and documents"
        subtitle="The records behind your relationships."
        actions={<button className="btn btn-md btn-primary" onClick={() => setCreating(true)}><PlusIcon size={18} /> New {label.one.toLowerCase()}</button>}
      />
      <div className="animate-enter space-y-3" style={{ animationDelay: "60ms" }}>
        <div className="-mx-1 overflow-x-auto px-1 pb-1">
          <Segmented kind="tab" label="Kind" value={kind} onChange={(k) => { setSort(SORTS[k][0].value); navigate(`crm/${k}s`); }} options={KINDS.map((k) => ({ id: k, label: KIND_LABEL[k].many }))} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-52 max-w-sm flex-1">
            <SearchIcon size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
            <input className="field h-10 w-full pl-9" placeholder={`Search ${label.many.toLowerCase()}`} aria-label={`Search ${label.many.toLowerCase()}`} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <Select label="Sort by" value={sort} onChange={setSort} options={SORTS[kind]} />
        </div>
        {!data && <Skeleton className="h-64 w-full rounded-xl" />}
        {data && data.items.length === 0 && <Empty icon={ICON[kind]} title={dq ? "No matches" : `No ${label.many.toLowerCase()} yet`}>{dq ? "Try a different search." : `${label.many} appear here as you add them or import notes.`}</Empty>}
        {data && data.items.length > 0 && (
          <div className="panel divide-y divide-line overflow-hidden">
            {data.items.map((e) => (
              <a key={e.id} href={`#/crm/e/${e.id}`} className="flex items-center gap-3.5 px-5 py-3 transition-colors duration-150 hover:bg-forest/[.05]">
                <span className="well">{ICON[kind] && (kind === "meeting" ? <CalendarIcon size={16} /> : kind === "document" ? <DocIcon size={16} /> : <TopicIcon size={16} />)}</span>
                <div className="min-w-0 flex-1">
                  <div className="line-clamp-2 text-label font-medium">{e.name}</div>
                  <div className="truncate text-hint text-ink-soft">{e.subtitle ?? (e.summary ? e.summary.slice(0, 120) : " ")}</div>
                </div>
                <div className="hidden shrink-0 gap-1 sm:flex"><Tags tags={e.tags} max={2} /></div>
                <div className="w-28 shrink-0 text-right text-meta text-ink-soft">
                  <div className="text-ink">{e.occurred_at ? formatDate(e.occurred_at) : ""}</div>
                  <div className="tabular-nums">{e.degree} connection{e.degree === 1 ? "" : "s"}</div>
                </div>
              </a>
            ))}
            {data.items.length < data.total && (
              <div className="p-2 text-center"><button className="btn btn-sm btn-ghost" onClick={() => setLimit((l) => l + 100)}>Show more ({data.total - data.items.length} left)</button></div>
            )}
          </div>
        )}
      </div>
      {creating && <EntityFormDialog kind={kind} onClose={() => setCreating(false)} onSaved={(e) => navigate(`crm/e/${e.id}`)} />}
    </>
  );
}
