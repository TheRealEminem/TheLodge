// The network: how the people you know connect, and what groups them. Only people are nodes; organizations,
// topics and tags are groups you switch on to pull their people together; meetings and documents show when you
// select someone. Presets ask it focused questions ("who could introduce me to X?") and the AI writes more. Also a
// path finder ("how do I reach X?").
import { Suspense, lazy, useMemo, useState } from "react";
import { CloseIcon, NetworkIcon, SignpostIcon } from "@core/components/icons";
import { PageHeader, Segmented, Select, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { navigate, useQueryParams } from "@core/router";
import { crmApi } from "./api";
import type { NetGroup, NetNode } from "./api";
import { Empty } from "./bits";
import { PathChains } from "./cards";
import { EntityPicker } from "./forms";
import { GraphLegend } from "./GraphLegend";
import { GROUP_META, groupMap } from "./groups";
import type { Highlight } from "./NetworkCanvas";
import { GroupBar, GroupPanel, PersonPanel, PicksPanel } from "./NetworkPanels";
import { AskPanel, PresetBar, PresetPanel } from "./NetworkPresets";
import type { ActivePreset } from "./NetworkPresets";
import { TIER_META } from "./tier";

const NetworkCanvas = lazy(() => import("./NetworkCanvas"));
const PRESET = "preset"; // the preset on screen, drawn as one more group

export default function Network() {
  const [params, setParams] = useQueryParams();
  const focus = params.get("focus");
  const pathTo = params.get("to");
  const depth = Number(params.get("depth") ?? 2);
  const wellsParam = params.get("wells") ?? "";
  const [view, setView] = useState<"graph" | "list">("graph");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [hoverWell, setHoverWell] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [pathIndex, setPathIndex] = useState(0);
  const [preset, setPreset] = useState<ActivePreset | null>(null);
  const [asking, setAsking] = useState(false);

  const { data: net, error } = useLive(() => crmApi.network({ focus: focus ?? undefined, depth, max_nodes: 600 }), [focus, depth]);
  const { data: me } = useLive(crmApi.me);
  const { data: paths } = useLive(() => (pathTo && me ? crmApi.netPaths({ target: pathTo }) : Promise.resolve(null)), [pathTo, me?.id]);
  const { data: focusEntity } = useLive(() => (focus ? crmApi.entity(focus) : Promise.resolve(null)), [focus]);
  const { data: evidence } = useLive(() => (selectedId ? crmApi.evidence(selectedId) : Promise.resolve(null)), [selectedId]);
  const presetKey = preset ? JSON.stringify(preset.spec) : "";
  const { data: found, error: presetError } = useLive(() => (preset ? crmApi.runPreset(preset.spec) : Promise.resolve(null)), [presetKey]);

  const baseGroups = useMemo(() => groupMap(net?.groups), [net?.groups]);
  const wells = useMemo(() => wellsParam.split(",").filter((g) => g && baseGroups.has(g)), [wellsParam, baseGroups]);
  // The preset's people are pulled together like a group's, and everyone else fades.
  const shown = found && preset ? found : null;
  const groups = useMemo(() => {
    if (!shown) return baseGroups;
    const m = new Map(baseGroups);
    m.set(PRESET, { id: PRESET, kind: "preset", name: shown.title, size: shown.people.length, ref: null } satisfies NetGroup);
    return m;
  }, [baseGroups, shown]);
  const nodes = useMemo(() => {
    const ids = new Set(shown?.people.map((p) => p.id));
    return (net?.nodes ?? []).map((n) => (ids.has(n.id) ? { ...n, groups: [...n.groups, PRESET] } : n));
  }, [net?.nodes, shown]);
  const shownWells = useMemo(() => (shown ? [...wells, PRESET] : wells), [wells, shown]);
  const showMe = params.get("me") === "1" || Boolean(pathTo) || Boolean(focus && focus === me?.id);
  const active = paths?.paths[pathIndex] ?? paths?.paths[0];
  const highlight: Highlight | null = useMemo(() => (active ? { nodes: new Set(active.nodes.map((n) => n.id)), links: new Set(active.links.map((l) => l.id)) } : null), [active]);
  const selected = nodes.find((n) => n.id === selectedId) ?? null;
  const pickedPeople = useMemo(() => nodes.filter((n) => picked.has(n.id)), [nodes, picked]);

  const setWells = (next: string[]) => setParams({ wells: next.join(",") || null });
  const toggleWell = (gid: string) => setWells(wells.includes(gid) ? wells.filter((w) => w !== gid) : [...wells, gid]);
  const select = (id: string | null) => { setSelectedId(id); if (id) setOpenGroup(null); };
  const clickNode = (n: NetNode, e: MouseEvent) => {
    if (e.shiftKey || e.metaKey || e.ctrlKey) {
      setPicked((p) => { const next = new Set(p); if (next.has(n.id)) next.delete(n.id); else next.add(n.id); return next; });
    } else select(n.id);
  };
  const side = Boolean(selected || pathTo || openGroup || picked.size || preset || asking);

  const listed = useMemo(() => {
    const inWell = (n: NetNode) => !shownWells.length || shownWells.some((w) => n.groups.includes(w));
    return nodes.filter((n) => (showMe || !n.is_self) && inWell(n));
  }, [nodes, shownWells, showMe]);

  return (
    <>
      <PageHeader
        title="Network"
        subtitle={focusEntity ? `Around ${focusEntity.entity.name}` : "How the people you know connect, and what groups them."}
        actions={<Segmented label="View" value={view} onChange={setView} options={[{ id: "graph", label: "Graph" }, { id: "list", label: "List" }]} />}
      />

      <PresetBar onRun={(p) => { setPreset(p); setSelectedId(null); }} asking={asking} onAsk={() => setAsking((a) => !a)} />

      {net && (
        <GroupBar
          groups={net.groups}
          active={wells}
          hovered={hoverWell}
          openGroup={openGroup}
          onToggle={toggleWell}
          onHover={setHoverWell}
          onOpen={(gid) => { setOpenGroup(gid); setSelectedId(null); }}
          onApply={setWells}
        />
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button
          aria-pressed={showMe}
          disabled={Boolean(pathTo)}
          onClick={() => setParams({ me: params.get("me") === "1" ? null : "1" })}
          className={`chip h-7 px-2.5 ${showMe ? "bg-forest-soft text-forest-deep" : "bg-surface-subtle text-ink-soft"}`}
          data-tip="Draw the lines from you to everyone you know"
        >
          Your ties
        </button>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {focus ? (
            <>
              <Select label="Depth" size="sm" value={String(depth)} onChange={(v) => setParams({ depth: v })} options={[1, 2, 3].map((d) => ({ value: String(d), label: `${d} hop${d > 1 ? "s" : ""}` }))} />
              <button className="btn btn-sm btn-soft" onClick={() => setParams({ focus: null })}><CloseIcon size={16} /> Everyone</button>
            </>
          ) : (
            <div className="w-56"><EntityPicker kinds={["person"]} placeholder="Focus on someone…" onSelect={(e) => { setParams({ focus: e.id }); select(e.id); }} /></div>
          )}
          {me && <div className="w-56"><EntityPicker kinds={["person"]} placeholder="Find path to…" exclude={[me.id]} onSelect={(e) => { setPathIndex(0); setParams({ to: e.id }); }} /></div>}
        </div>
      </div>

      <div className={`grid gap-4 ${side ? "lg:grid-cols-[minmax(0,1fr)_21rem]" : ""}`}>
        <div className="panel relative overflow-hidden" style={{ height: "clamp(440px, 66vh, 760px)" }}>
          {error && <p className="p-5 text-ui text-trail-deep">{error}</p>}
          {!net && !error && <Skeleton className="h-full w-full" />}
          {net && net.nodes.length === 0 && <div className="grid h-full place-items-center p-6"><Empty icon={<NetworkIcon size={20} />} title="Nothing to show yet">Add people and how they connect and they appear here.</Empty></div>}
          {net && net.nodes.length > 0 && view === "graph" && (
            <Suspense fallback={<Skeleton className="h-full w-full" />}>
              <NetworkCanvas
                nodes={nodes}
                links={net.links}
                groups={groups}
                wells={shownWells}
                showMe={showMe}
                evidence={selectedId ? evidence : null}
                selectedId={selectedId}
                picked={picked}
                focusId={focus}
                highlight={highlight}
                hoverWell={hoverWell}
                onNodeClick={clickNode}
                onEventClick={(e) => navigate(`crm/e/${e.id}`)}
                onBackgroundClick={() => select(null)}
              />
            </Suspense>
          )}
          {net && net.nodes.length > 0 && view === "list" && <PeopleList people={listed} groups={groups} onPick={(n) => select(n.id)} />}
          {view === "graph" && (
            <div className="pointer-events-none absolute bottom-3 left-3 right-3 flex flex-col items-start gap-1.5">
              <div className="panel pointer-events-auto px-3 py-2"><GraphLegend wells={wells.length > 0} preset={Boolean(shown)} events={Boolean(selectedId)} /></div>
              {net?.truncated && <div className="panel bg-sun-soft px-3 py-1.5 text-meta text-sun-deep">Showing the most connected {net.nodes.length} people. Focus on someone to see more.</div>}
            </div>
          )}
        </div>

        {side && net && (
          <aside className="space-y-4">
            {preset && (
              <PresetPanel
                result={found}
                error={presetError}
                savedId={preset.savedId}
                onClose={() => setPreset(null)}
                onSelect={select}
                onPickAll={(ids) => setPicked(new Set(ids))}
              />
            )}
            {asking && <AskPanel onShow={(spec) => setPreset({ spec })} onClose={() => setAsking(false)} />}
            {pathTo && (
              <section className="panel p-4">
                <div className="mb-2 flex items-center justify-between">
                  <h2 className="flex items-center gap-1.5 text-heading font-semibold"><SignpostIcon size={16} /> Paths to {paths?.target.name ?? "…"}</h2>
                  <button className="icon-btn" aria-label="Close paths" onClick={() => setParams({ to: null })}><CloseIcon size={16} /></button>
                </div>
                {!paths ? <Skeleton className="h-12 w-full rounded-lg" /> : paths.paths.length ? <PathChains paths={paths.paths} activeIndex={pathIndex} onPick={setPathIndex} /> : <p className="text-ui text-ink-soft">No path within 4 hops.</p>}
              </section>
            )}
            {picked.size > 0 && <PicksPanel people={pickedPeople} onClear={() => setPicked(new Set())} onDone={() => undefined} />}
            {openGroup && groups.get(openGroup) && (
              <GroupPanel
                gid={openGroup}
                group={groups.get(openGroup)!}
                active={wells.includes(openGroup)}
                onClose={() => setOpenGroup(null)}
                onToggle={() => toggleWell(openGroup)}
                onSelect={select}
                onPickAll={(ids) => setPicked(new Set(ids))}
              />
            )}
            {selected && (
              <PersonPanel
                person={selected}
                links={net.links}
                nodes={nodes}
                groups={groups}
                active={wells}
                evidence={evidence}
                canPath={Boolean(me)}
                picked={picked.has(selected.id)}
                onClose={() => select(null)}
                onFocus={() => setParams({ focus: selected.id })}
                onPath={() => { setPathIndex(0); setParams({ to: selected.id }); }}
                onToggleGroup={toggleWell}
                onSelect={select}
                onEvent={(e) => navigate(`crm/e/${e.id}`)}
                onPick={() => setPicked((p) => { const next = new Set(p); if (next.has(selected.id)) next.delete(selected.id); else next.add(selected.id); return next; })}
              />
            )}
          </aside>
        )}
      </div>
    </>
  );
}

/** The same people as a list: readable by keyboard and screen reader, where the canvas isn't. */
function PeopleList({ people, groups, onPick }: { people: NetNode[]; groups: Map<string, { name: string; kind: keyof typeof GROUP_META }>; onPick: (n: NetNode) => void }) {
  const rows = [...people].sort((a, b) => b.degree - a.degree || a.name.localeCompare(b.name));
  return (
    <div className="h-full overflow-auto">
      <table className="w-full min-w-[560px] text-left text-ui">
        <caption className="sr-only">People in the network, most connected first</caption>
        <thead className="sticky top-0 bg-surface text-left text-ink-soft">
          <tr><th className="px-5 py-2 font-medium">Name</th><th className="px-3 py-2 font-medium">You know them</th><th className="px-3 py-2 font-medium">Groups</th><th className="px-5 py-2 text-right font-medium">Connections</th></tr>
        </thead>
        <tbody>
          {rows.map((n) => (
            <tr key={n.id} className="border-t border-line hover:bg-forest/[.05]">
              <td className="px-5 py-2"><button className="text-left font-medium hover:underline" onClick={() => onPick(n)}>{n.is_self ? `${n.name} (you)` : n.name}</button></td>
              <td className="px-3 py-2 text-ink-soft">{n.tier ? TIER_META[n.tier].label : "—"}</td>
              <td className="px-3 py-2 text-ink-soft">{n.groups.map((g) => groups.get(g)?.name).filter(Boolean).slice(0, 4).join(", ") || "—"}</td>
              <td className="px-5 py-2 text-right tabular-nums">{n.degree}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
