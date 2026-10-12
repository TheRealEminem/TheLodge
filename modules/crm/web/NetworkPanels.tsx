// The controls and side panels around the network canvas: switching groups on, saved views, and what you can
// say about a person, a group or a handful of people you've picked (including tagging them).
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { CheckIcon, CloseIcon, PlusIcon, SearchIcon, TrashIcon } from "@core/components/icons";
import { Select, Skeleton, useConfirm } from "@core/components/ui";
import { useLive } from "@core/live";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { Evidence, NetGroup, NetLink, NetNode, SavedView } from "./api";
import { Avatar } from "./bits";
import { Dialog } from "./forms";
import { GROUP_META, GROUP_ORDER, GroupGlyph } from "./groups";
import { TierBadge } from "./tier";

// ── Switching groups on ───────────────────────────────────────────────

export function GroupChip({ group, onOpen, onRemove, onHover, selected }: {
  group: NetGroup;
  onOpen: () => void;
  onRemove: () => void;
  onHover: (on: boolean) => void;
  selected?: boolean;
}) {
  return (
    <span
      className={`chip h-7 gap-1.5 pl-2.5 pr-1 ${selected ? "bg-forest-soft text-forest-deep" : "bg-surface-subtle text-ink"}`}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
    >
      <GroupGlyph kind={group.kind} className="text-forest" />
      <button className="font-medium hover:underline" onClick={onOpen} data-tip={`${GROUP_META[group.kind].one}: show who's in it`}>{group.name}</button>
      <span className="text-ink-soft tabular-nums">{group.size}</span>
      <button className="icon-btn !h-5 !w-5" aria-label={`Switch off ${group.name}`} onClick={onRemove}><CloseIcon size={12} /></button>
    </span>
  );
}

/** Search every group and switch one on. */
function GroupPicker({ groups, active, onAdd }: { groups: NetGroup[]; active: string[]; onAdd: (gid: string) => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const listId = useId();
  const found = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return groups.filter((g) => !active.includes(g.id) && (!needle || g.name.toLowerCase().includes(needle)))
      .sort((a, b) => GROUP_ORDER.indexOf(a.kind) - GROUP_ORDER.indexOf(b.kind) || b.size - a.size || a.name.localeCompare(b.name))
      .slice(0, 40);
  }, [groups, active, q]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  const choose = (g: NetGroup) => {
    onAdd(g.id);
    setQ("");
    setOpen(false);
  };
  return (
    <div ref={box} className="relative w-56">
      <SearchIcon size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
      <input
        className="field h-8 w-full pl-9 text-ui"
        placeholder="Add a group…"
        aria-label="Add a group"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        value={q}
        onFocus={() => setOpen(true)}
        onChange={(e) => { setQ(e.target.value); setOpen(true); setCursor(0); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(c + 1, found.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
          else if (e.key === "Enter" && found[cursor]) { e.preventDefault(); choose(found[cursor]); }
          else if (e.key === "Escape") { e.stopPropagation(); setOpen(false); }
        }}
      />
      {open && found.length > 0 && (
        <ul id={listId} role="listbox" className="panel absolute z-30 mt-1 max-h-80 w-72 animate-pop overflow-y-auto p-1 shadow-lg">
          {found.map((g, i) => (
            <li
              key={g.id}
              role="option"
              aria-selected={i === cursor}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(g)}
              onMouseEnter={() => setCursor(i)}
              className={`flex cursor-pointer items-center gap-2 rounded-sm px-2.5 py-2 text-ui ${i === cursor ? "bg-forest/[.07]" : ""}`}
            >
              <GroupGlyph kind={g.kind} className="text-forest" />
              <span className="truncate font-medium">{g.name}</span>
              <span className="ml-auto shrink-0 text-meta text-ink-soft">{GROUP_META[g.kind].one.toLowerCase()} · {g.size}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function GroupBar({ groups, active, hovered, openGroup, onToggle, onHover, onOpen, onApply }: {
  groups: NetGroup[];
  active: string[];
  hovered?: string | null;
  openGroup?: string | null;
  onToggle: (gid: string) => void;
  onHover: (gid: string | null) => void;
  onOpen: (gid: string) => void;
  onApply: (wells: string[]) => void;
}) {
  const byId = useMemo(() => new Map(groups.map((g) => [g.id, g])), [groups]);
  const suggestions = groups.filter((g) => !active.includes(g.id)).slice(0, 6);
  return (
    <div className="mb-3 animate-enter space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {active.map((gid) => {
          const g = byId.get(gid);
          return g ? <GroupChip key={gid} group={g} selected={openGroup === gid || hovered === gid} onOpen={() => onOpen(gid)} onRemove={() => onToggle(gid)} onHover={(on) => onHover(on ? gid : null)} /> : null;
        })}
        {active.length === 0 && <span className="text-ui text-ink-soft">Switch on a group to pull its people together.</span>}
        <GroupPicker groups={groups} active={active} onAdd={onToggle} />
        <ViewsMenu active={active} onApply={onApply} />
      </div>
      {suggestions.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-meta text-ink-soft">Biggest:</span>
          {suggestions.map((g) => (
            <button
              key={g.id}
              className="chip h-6 gap-1 border border-dashed border-line-strong bg-transparent px-2 text-ink-soft hover:bg-forest/[.05] hover:text-ink"
              onClick={() => onToggle(g.id)}
              onMouseEnter={() => onHover(g.id)}
              onMouseLeave={() => onHover(null)}
            >
              <PlusIcon size={12} /> {g.name} <span className="tabular-nums">{g.size}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Saved views ───────────────────────────────────────────────────────

function ViewsMenu({ active, onApply }: { active: string[]; onApply: (wells: string[]) => void }) {
  const { toast } = useShell();
  const { data: views } = useLive<SavedView[]>(crmApi.views);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [current, setCurrent] = useState<string>("");
  const [confirm, confirmDialog] = useConfirm();
  const applied = views?.find((v) => v.id === current);
  const save = async () => {
    try {
      const saved = await crmApi.saveView(name.trim(), active);
      setCurrent(saved.id);
      setNaming(false);
      setName("");
      toast(`Saved “${saved.name}”`, "success");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const remove = async () => {
    if (!applied || !(await confirm({ title: `Delete “${applied.name}”?`, body: "The groups themselves aren't touched, only this saved set.", confirmLabel: "Delete", tone: "danger" }))) return;
    await crmApi.deleteView(applied.id).catch((e) => toast((e as Error).message, "error"));
    setCurrent("");
  };
  return (
    <>
      {(views?.length ?? 0) > 0 && (
        <Select
          label="Saved views"
          size="sm"
          className="w-44"
          value={current}
          options={[{ value: "", label: "Saved views" }, ...(views ?? []).map((v) => ({ value: v.id, label: v.name, hint: `${v.wells.length} group${v.wells.length === 1 ? "" : "s"}` }))]}
          onChange={(id) => { setCurrent(id); const v = views?.find((x) => x.id === id); if (v) onApply(v.wells); }}
        />
      )}
      {applied && <button className="icon-btn" aria-label={`Delete saved view ${applied.name}`} data-tip="Delete this saved view" onClick={() => void remove()}><TrashIcon size={16} /></button>}
      {active.length > 0 && <button className="btn btn-sm btn-ghost" onClick={() => { setName(applied?.name ?? ""); setNaming(true); }}>Save view</button>}
      {naming && (
        <Dialog title="Save this view" onClose={() => setNaming(false)} width={420}>
          <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) void save(); }} className="space-y-4">
            <p className="text-ui text-ink-soft">Remembers which groups are switched on, so you can come back to this arrangement.</p>
            <input className="field w-full" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Hardware mentors" aria-label="View name" maxLength={80} />
            <div className="flex justify-end gap-2">
              <button type="button" className="btn btn-soft" onClick={() => setNaming(false)}>Cancel</button>
              <button className="btn btn-primary" disabled={!name.trim()}>Save</button>
            </div>
          </form>
        </Dialog>
      )}
      {confirmDialog}
    </>
  );
}

// ── Tags ──────────────────────────────────────────────────────────────

/** Add or remove tags on one or several people. Tags are free text; a tag with two or more people is a group. */
export function TagEditor({ ids, current, onDone }: { ids: string[]; current: string[]; onDone?: () => void }) {
  const { toast } = useShell();
  const [text, setText] = useState("");
  const { data: known } = useLive(crmApi.tagNames);
  const suggestions = (known ?? []).filter((t) => !current.includes(t.tag) && (!text || t.tag.includes(text.trim().toLowerCase().replace(/\s+/g, "-")))).slice(0, 6);
  const change = async (add: string[], remove: string[]) => {
    try {
      await crmApi.retag({ ids, add, remove });
      setText("");
      onDone?.();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <div>
      {current.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {current.map((t) => (
            <span key={t} className="chip h-6 gap-1 bg-surface-subtle pl-2 pr-1 text-ink-soft">
              #{t}
              <button className="icon-btn !h-4 !w-4" aria-label={`Remove tag ${t}`} onClick={() => void change([], [t])}><CloseIcon size={12} /></button>
            </span>
          ))}
        </div>
      )}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) void change([text.trim()], []); }}>
        <input className="field h-8 min-w-0 flex-1 text-ui" value={text} onChange={(e) => setText(e.target.value)} placeholder={ids.length > 1 ? `Tag all ${ids.length} as…` : "Add a tag…"} aria-label="Add a tag" maxLength={64} />
        <button className="btn btn-sm btn-soft" disabled={!text.trim()}><PlusIcon size={16} /> Add</button>
      </form>
      {suggestions.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {suggestions.map((t) => (
            <button key={t.tag} className="chip h-6 border border-dashed border-line-strong bg-transparent px-2 text-ink-soft hover:bg-forest/[.05]" onClick={() => void change([t.tag], [])}>
              #{t.tag} <span className="tabular-nums">{t.count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Side panels ───────────────────────────────────────────────────────

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div className="mt-4 border-t border-line pt-3">
    <h3 className="mb-1.5 text-label font-semibold">{title}</h3>
    {children}
  </div>
);

export function PersonPanel({ person, links, nodes, groups, active, evidence, canPath, onClose, onFocus, onPath, onToggleGroup, onSelect, onEvent, onPick, picked }: {
  person: NetNode;
  links: NetLink[];
  nodes: NetNode[];
  groups: Map<string, NetGroup>;
  active: string[];
  evidence: Evidence[] | null | undefined;
  canPath: boolean;
  onClose: () => void;
  onFocus: () => void;
  onPath: () => void;
  onToggleGroup: (gid: string) => void;
  onSelect: (id: string) => void;
  onEvent: (e: Evidence) => void;
  onPick: () => void;
  picked: boolean;
}) {
  const names = useMemo(() => new Map(nodes.map((n) => [n.id, n.name])), [nodes]);
  const lines = useMemo(
    () => links.filter((l) => l.source === person.id || l.target === person.id).sort((a, b) => b.weight - a.weight).slice(0, 8),
    [links, person.id],
  );
  return (
    <section className="panel p-4">
      <div className="flex items-start gap-3">
        <Avatar name={person.name} size={40} />
        <div className="min-w-0 flex-1">
          <div className="text-label font-semibold">{person.name}</div>
          {person.subtitle && <div className="text-ui text-ink-soft">{person.subtitle}</div>}
          <div className="mt-0.5 flex items-center gap-2 text-meta text-ink-soft">
            {person.degree} connection{person.degree === 1 ? "" : "s"}
            {person.tier && <TierBadge tier={person.tier} />}
          </div>
        </div>
        <button className="icon-btn" aria-label="Close" onClick={onClose}><CloseIcon size={16} /></button>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <a className="btn btn-sm btn-primary" href={`#/crm/e/${person.id}`}>Open profile</a>
        <button className="btn btn-sm btn-soft" onClick={onFocus}>Focus</button>
        {canPath && !person.is_self && <button className="btn btn-sm btn-soft" onClick={onPath}>Path from me</button>}
        <button className="btn btn-sm btn-ghost" onClick={onPick}>{picked ? "Unpick" : "Pick"}</button>
      </div>

      {person.groups.length > 0 && (
        <Section title="Groups">
          <div className="flex flex-wrap gap-1.5">
            {person.groups.map((gid) => {
              const g = groups.get(gid);
              if (!g) return null;
              const on = active.includes(gid);
              return (
                <button
                  key={gid}
                  aria-pressed={on}
                  onClick={() => onToggleGroup(gid)}
                  className={`chip h-6 gap-1 px-2 ${on ? "bg-forest-soft text-forest-deep" : "bg-surface-subtle text-ink-soft hover:text-ink"}`}
                  data-tip={on ? "Switch this group off" : "Switch this group on"}
                >
                  <GroupGlyph kind={g.kind} size={12} /> {g.name}
                </button>
              );
            })}
          </div>
        </Section>
      )}

      <Section title="Tags">
        <TagEditor ids={[person.id]} current={person.tags} />
      </Section>

      {lines.length > 0 && (
        <Section title="Why they're connected">
          <ul className="space-y-2">
            {lines.map((l) => {
              const other = l.source === person.id ? l.target : l.source;
              return (
                <li key={l.id} className="text-ui">
                  <button className="font-medium hover:underline" onClick={() => onSelect(other)}>{names.get(other) ?? "Someone"}</button>
                  <span className="text-ink-soft"> · {l.why[0]?.text}{l.why.length > 1 ? ` and ${l.why.length - 1} more` : ""}</span>
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      <Section title="Meetings and documents">
        {evidence === undefined || evidence === null ? (
          <Skeleton className="h-10 w-full rounded-lg" />
        ) : evidence.length === 0 ? (
          <p className="text-ui text-ink-soft">Nothing recorded yet.</p>
        ) : (
          <ul className="space-y-1.5">
            {evidence.slice(0, 14).map((e) => (
              <li key={e.id} className="text-ui">
                <button className="text-left font-medium hover:underline" onClick={() => onEvent(e)}>{e.name}</button>
                <span className="text-ink-soft"> · {e.kind === "meeting" ? "meeting" : "document"}{e.at ? `, ${e.at.slice(0, 10)}` : ""}{e.role === "came up" ? ", came up" : ""}</span>
              </li>
            ))}
            {evidence.length > 14 && <li className="text-meta text-ink-soft">and {evidence.length - 14} more on their profile</li>}
          </ul>
        )}
      </Section>
    </section>
  );
}

export function GroupPanel({ gid, group, active, onClose, onToggle, onSelect, onPickAll }: {
  gid: string;
  group: NetGroup;
  active: boolean;
  onClose: () => void;
  onToggle: () => void;
  onSelect: (id: string) => void;
  onPickAll: (ids: string[]) => void;
}) {
  const { data } = useLive(() => crmApi.group(gid), [gid]);
  return (
    <section className="panel p-4">
      <div className="flex items-start gap-3">
        <span className="well well-forest"><GroupGlyph kind={group.kind} size={16} /></span>
        <div className="min-w-0 flex-1">
          <div className="text-label font-semibold">{group.name}</div>
          <div className="text-meta text-ink-soft">{GROUP_META[group.kind].one} · {group.size} {group.size === 1 ? "person" : "people"}</div>
        </div>
        <button className="icon-btn" aria-label="Close" onClick={onClose}><CloseIcon size={16} /></button>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn btn-sm btn-soft" onClick={onToggle}>{active ? "Switch off" : "Switch on"}</button>
        {data && <button className="btn btn-sm btn-ghost" onClick={() => onPickAll(data.members.map((m) => m.id))}>Pick everyone</button>}
        {group.ref && <a className="btn btn-sm btn-ghost" href={`#/crm/e/${group.ref}`}>Open record</a>}
      </div>
      <div className="mt-3 border-t border-line pt-2">
        {!data ? <Skeleton className="h-16 w-full rounded-lg" /> : (
          <ul className="max-h-72 space-y-1.5 overflow-y-auto">
            {data.members.map((m) => (
              <li key={m.id} className="flex items-baseline gap-2 text-ui">
                <button className="truncate font-medium hover:underline" onClick={() => onSelect(m.id)}>{m.name}</button>
                <span className="truncate text-meta text-ink-soft">{m.why}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

export function PicksPanel({ people, onClear, onDone }: { people: NetNode[]; onClear: () => void; onDone: () => void }) {
  return (
    <section className="panel p-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 text-heading font-semibold"><CheckIcon size={16} /> {people.length} picked</h2>
        <button className="btn btn-sm btn-ghost" onClick={onClear}>Clear</button>
      </div>
      <p className="mt-1 text-hint text-ink-soft">Shift-click people to pick more. Give them a tag and the tag becomes a group you can switch on.</p>
      <div className="mt-3"><TagEditor ids={people.map((p) => p.id)} current={[]} onDone={onDone} /></div>
      <ul className="mt-3 max-h-40 space-y-0.5 overflow-y-auto text-ui text-ink-soft">
        {people.map((p) => <li key={p.id} className="truncate">{p.name}</li>)}
      </ul>
    </section>
  );
}
