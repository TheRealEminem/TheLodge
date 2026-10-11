// The whole network, or one record's neighborhood, with a path finder ("how do I reach X?").
import { Suspense, lazy, useMemo, useState } from "react";
import { CloseIcon, NetworkIcon, SignpostIcon } from "@core/components/icons";
import { PageHeader, Segmented, Select, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { useQueryParams } from "@core/router";
import { crmApi } from "./api";
import type { EntityKind, Graph, GraphNode } from "./api";
import { Avatar, Empty, KIND_LABEL } from "./bits";
import { PathChains } from "./cards";
import { EntityPicker } from "./forms";
import { KIND_ORDER, KIND_SHAPE, ShapeGlyph } from "./graphShapes";
import { GraphLegend } from "./GraphLegend";
import type { Highlight } from "./NetworkCanvas";
import { TIER_META, TierBadge } from "./tier";

const NetworkCanvas = lazy(() => import("./NetworkCanvas"));

const DEFAULT_KINDS: EntityKind[] = ["person", "organization", "meeting", "topic"];

export default function Network() {
  const [params, setParams] = useQueryParams();
  const focus = params.get("focus");
  const pathTo = params.get("to");
  const depth = Number(params.get("depth") ?? 2);
  const kinds = (params.get("kinds")?.split(",").filter(Boolean) as EntityKind[] | undefined) ?? DEFAULT_KINDS;
  const [view, setView] = useState<"graph" | "list">("graph");
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [pathIndex, setPathIndex] = useState(0);
  const [peopleOnly, setPeopleOnly] = useState(false);

  const { data: graph, error } = useLive(
    () => crmApi.graph({ center: focus ?? undefined, depth, kinds: kinds.join(","), max_nodes: 600 }),
    [focus, depth, kinds.join(",")],
  );
  const { data: me } = useLive(crmApi.me);
  const { data: paths } = useLive(() => (pathTo && me ? crmApi.paths({ target: pathTo, through: peopleOnly ? "person" : undefined }) : Promise.resolve(null)), [pathTo, peopleOnly, me?.id]);
  const { data: focusEntity } = useLive(() => (focus ? crmApi.entity(focus) : Promise.resolve(null)), [focus]);
  const active = paths?.paths[pathIndex] ?? paths?.paths[0];

  // Make sure every node on the highlighted path is drawn, even if its kind is filtered out.
  const shown: Graph | undefined = useMemo(() => {
    if (!graph || !active) return graph ?? undefined;
    const ids = new Set(graph.nodes.map((n) => n.id));
    const linkIds = new Set(graph.links.map((l) => l.id));
    return { ...graph, nodes: [...graph.nodes, ...active.nodes.filter((n) => !ids.has(n.id))], links: [...graph.links, ...active.links.filter((l) => !linkIds.has(l.id))] };
  }, [graph, active]);
  const highlight: Highlight | null = active ? { nodes: new Set(active.nodes.map((n) => n.id)), links: new Set(active.links.map((l) => l.id)) } : null;

  const toggleKind = (k: EntityKind) => {
    const next = kinds.includes(k) ? kinds.filter((x) => x !== k) : [...kinds, k];
    if (next.length) setParams({ kinds: KIND_ORDER.filter((x) => next.includes(x)).join(",") });
  };
  const side = Boolean(selected || pathTo);

  return (
    <>
      <PageHeader
        title="Network"
        subtitle={focusEntity ? `Around ${focusEntity.entity.name}` : "Everyone and everything you've connected."}
        actions={<Segmented label="View" value={view} onChange={setView} options={[{ id: "graph", label: "Graph" }, { id: "list", label: "List" }]} />}
      />
      <div className="mb-3 flex animate-enter flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show kinds">
          {KIND_ORDER.map((k) => (
            <button
              key={k}
              aria-pressed={kinds.includes(k)}
              onClick={() => toggleKind(k)}
              className={`chip h-7 gap-1.5 px-2.5 ${kinds.includes(k) ? "bg-forest-soft text-forest-deep" : "bg-surface-subtle text-ink-soft"}`}
            >
              <ShapeGlyph shape={KIND_SHAPE[k]} /> {KIND_LABEL[k].many}
            </button>
          ))}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {focus ? (
            <>
              <Select label="Depth" size="sm" value={String(depth)} onChange={(v) => setParams({ depth: v })} options={[1, 2, 3].map((d) => ({ value: String(d), label: `${d} hop${d > 1 ? "s" : ""}` }))} />
              <button className="btn btn-sm btn-soft" onClick={() => setParams({ focus: null })}><CloseIcon size={16} /> Whole network</button>
            </>
          ) : (
            <div className="w-56"><EntityPicker placeholder="Focus on…" onSelect={(e) => setParams({ focus: e.id })} /></div>
          )}
          {me && <div className="w-56"><EntityPicker placeholder="Find path to…" exclude={[me.id]} onSelect={(e) => { setPathIndex(0); setParams({ to: e.id }); }} /></div>}
        </div>
      </div>

      <div className={`grid gap-4 ${side ? "lg:grid-cols-[minmax(0,1fr)_20rem]" : ""}`}>
        <div className="panel relative overflow-hidden" style={{ height: "clamp(420px, 64vh, 720px)" }}>
          {error && <p className="p-5 text-ui text-trail-deep">{error}</p>}
          {!graph && !error && <Skeleton className="h-full w-full" />}
          {graph && graph.nodes.length === 0 && <div className="grid h-full place-items-center p-6"><Empty icon={<NetworkIcon size={20} />} title="Nothing to show yet">Add people and relationships and they appear here.</Empty></div>}
          {shown && shown.nodes.length > 0 && view === "graph" && (
            <Suspense fallback={<Skeleton className="h-full w-full" />}>
              <NetworkCanvas graph={shown} focusId={focus} selectedId={selected?.id} highlight={highlight} onNodeClick={setSelected} onBackgroundClick={() => setSelected(null)} />
            </Suspense>
          )}
          {shown && shown.nodes.length > 0 && view === "list" && <NodeList graph={shown} onPick={setSelected} />}
          {view === "graph" && (
            <div className="pointer-events-none absolute bottom-3 left-3 right-3 flex flex-col items-start gap-1.5">
              <div className="panel pointer-events-auto px-3 py-2"><GraphLegend kinds={kinds} /></div>
              {graph?.truncated && <div className="panel bg-sun-soft px-3 py-1.5 text-meta text-sun-deep">Showing the most connected {graph.nodes.length} records. Focus on someone to see more.</div>}
            </div>
          )}
        </div>

        {side && (
          <aside className="space-y-4">
            {pathTo && (
              <section className="panel p-4">
                <div className="mb-2 flex items-center justify-between">
                  <h2 className="flex items-center gap-1.5 text-heading font-semibold"><SignpostIcon size={16} /> Paths to {paths?.target.name ?? "…"}</h2>
                  <button className="icon-btn" aria-label="Close paths" onClick={() => setParams({ to: null })}><CloseIcon size={16} /></button>
                </div>
                <label className="mb-2.5 flex items-center gap-1.5 text-hint text-ink-soft">
                  <input type="checkbox" className="accent-forest" checked={peopleOnly} onChange={(e) => { setPeopleOnly(e.target.checked); setPathIndex(0); }} /> Only through people
                </label>
                {!paths ? <Skeleton className="h-12 w-full rounded-lg" /> : paths.paths.length ? <PathChains paths={paths.paths} activeIndex={pathIndex} onPick={setPathIndex} /> : <p className="text-ui text-ink-soft">No path within 4 hops.</p>}
              </section>
            )}
            {selected && (
              <section className="panel p-4">
                <div className="flex items-start gap-3">
                  <Avatar name={selected.name} kind={selected.kind} size={40} />
                  <div className="min-w-0 flex-1">
                    <div className="text-label font-semibold">{selected.name}</div>
                    {selected.subtitle && <div className="text-ui text-ink-soft">{selected.subtitle}</div>}
                    <div className="mt-0.5 flex items-center gap-2 text-meta text-ink-soft">
                      {KIND_LABEL[selected.kind].one} · {selected.degree} connection{selected.degree === 1 ? "" : "s"}
                      {selected.tier && <TierBadge tier={selected.tier} />}
                    </div>
                  </div>
                  <button className="icon-btn" aria-label="Close" onClick={() => setSelected(null)}><CloseIcon size={16} /></button>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <a className="btn btn-sm btn-primary" href={`#/crm/e/${selected.id}`}>Open profile</a>
                  <button className="btn btn-sm btn-soft" onClick={() => setParams({ focus: selected.id })}>Focus</button>
                  {me && !selected.is_self && <button className="btn btn-sm btn-soft" onClick={() => { setPathIndex(0); setParams({ to: selected.id }); }}>Path from me</button>}
                </div>
              </section>
            )}
          </aside>
        )}
      </div>
    </>
  );
}

/** The same records as a list: readable by keyboard and screen reader, where the canvas isn't. */
function NodeList({ graph, onPick }: { graph: Graph; onPick: (n: GraphNode) => void }) {
  const rows = [...graph.nodes].sort((a, b) => b.degree - a.degree || a.name.localeCompare(b.name));
  return (
    <div className="h-full overflow-auto">
      <table className="w-full min-w-[480px] text-left text-ui">
        <caption className="sr-only">Records in the network, most connected first</caption>
        <thead className="sticky top-0 bg-surface text-left text-ink-soft">
          <tr><th className="px-5 py-2 font-medium">Name</th><th className="px-3 py-2 font-medium">Kind</th><th className="px-3 py-2 font-medium">You know them</th><th className="px-5 py-2 text-right font-medium">Connections</th></tr>
        </thead>
        <tbody>
          {rows.map((n) => (
            <tr key={n.id} className="border-t border-line hover:bg-forest/[.05]">
              <td className="px-5 py-2"><button className="text-left font-medium hover:underline" onClick={() => onPick(n)}>{n.is_self ? `${n.name} (you)` : n.name}</button></td>
              <td className="px-3 py-2 text-ink-soft">{KIND_LABEL[n.kind].one}</td>
              <td className="px-3 py-2 text-ink-soft">{n.tier ? TIER_META[n.tier].label : "—"}</td>
              <td className="px-5 py-2 text-right tabular-nums">{n.degree}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
