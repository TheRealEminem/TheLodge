// Dialogs and forms: a plain dialog, a search-as-you-type picker, create/edit, merge, and add-a-relationship.
import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { CloseIcon, PlusIcon, SearchIcon } from "@core/components/icons";
import { Select } from "@core/components/ui";
import { useLive } from "@core/live";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { Entity, EntityKind, EntitySummary, RelKindInfo } from "./api";
import { ATTRIBUTE_FIELDS, KIND_LABEL, StrengthDots, useDebounced } from "./bits";

/** The dialog the confirm uses, with room for a form. Esc or a click outside closes it. */
export function Dialog({ title, onClose, children, width = 520 }: { title: string; onClose: () => void; children: ReactNode; width?: number }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  // In a portal: an ancestor with an entrance animation would otherwise become the "fixed" box.
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex animate-fade-in items-center justify-center bg-[var(--scrim)] p-5 backdrop-blur-[3px]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="flex max-h-[90vh] w-full animate-dialog-in flex-col rounded-xl border border-line bg-surface shadow-lg"
        style={{ maxWidth: width }}
      >
        <header className="flex items-center justify-between border-b border-line px-6 py-4">
          <h2 className="text-lead font-semibold tracking-[-0.01em]">{title}</h2>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>
            <CloseIcon size={18} />
          </button>
        </header>
        <div className="overflow-y-auto p-6">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-ui font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-hint text-ink-soft">{hint}</span>}
    </label>
  );
}

/** Search-as-you-type over entities. onCreate adds a "Create “name”" choice. */
export function EntityPicker({ kinds, onSelect, onCreate, placeholder = "Search", exclude = [], autoFocus }: {
  kinds?: EntityKind[];
  onSelect: (e: EntitySummary) => void;
  onCreate?: (name: string) => void;
  placeholder?: string;
  exclude?: string[];
  autoFocus?: boolean;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const dq = useDebounced(q, 180);
  const listId = useId();
  const box = useRef<HTMLDivElement>(null);
  const { data } = useLive(
    () => (open ? crmApi.entities({ kind: kinds?.join(","), q: dq || undefined, limit: 8, sort: dq ? "name" : "updated" }) : Promise.resolve(null)),
    [open, dq, kinds?.join(",")],
  );
  const items = (data?.items ?? []).filter((e) => !exclude.includes(e.id));
  const showCreate = Boolean(onCreate && q.trim() && !items.some((e) => e.name.toLowerCase() === q.trim().toLowerCase()));
  const total = items.length + (showCreate ? 1 : 0);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const choose = (i: number) => {
    if (i < items.length) {
      const e = items[i];
      onSelect({ id: e.id, kind: e.kind, name: e.name, subtitle: e.subtitle, occurred_at: e.occurred_at, is_self: e.is_self });
    } else if (showCreate) onCreate?.(q.trim());
    setQ("");
    setOpen(false);
  };

  return (
    <div ref={box} className="relative">
      <SearchIcon size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
      <input
        className="field h-10 w-full pl-9"
        value={q}
        placeholder={placeholder}
        aria-label={placeholder}
        autoFocus={autoFocus}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        onFocus={() => setOpen(true)}
        onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, total - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          else if (e.key === "Enter" && total > 0) { e.preventDefault(); choose(active); }
          else if (e.key === "Escape") { e.stopPropagation(); setOpen(false); }
        }}
      />
      {open && total > 0 && (
        <ul id={listId} role="listbox" className="panel absolute z-30 mt-1 max-h-72 w-full animate-pop overflow-y-auto p-1 shadow-lg">
          {items.map((e, i) => (
            <li
              key={e.id}
              role="option"
              aria-selected={i === active}
              onMouseDown={(ev) => ev.preventDefault()}
              onClick={() => choose(i)}
              onMouseEnter={() => setActive(i)}
              className={`flex cursor-pointer items-baseline gap-2 rounded-sm px-2.5 py-2 text-ui ${i === active ? "bg-forest/[.07]" : ""}`}
            >
              <span className="truncate font-medium">{e.name}</span>
              {e.subtitle && <span className="truncate text-ink-soft">{e.subtitle}</span>}
            </li>
          ))}
          {showCreate && (
            <li
              role="option"
              aria-selected={active === items.length}
              onMouseDown={(ev) => ev.preventDefault()}
              onClick={() => choose(items.length)}
              onMouseEnter={() => setActive(items.length)}
              className={`flex cursor-pointer items-center gap-2 rounded-sm px-2.5 py-2 text-ui font-medium text-forest-deep ${active === items.length ? "bg-forest/[.07]" : ""}`}
            >
              <PlusIcon size={16} /> Create “{q.trim()}”
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

const toLocalInput = (iso: string | null | undefined) => {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

/** Create (no `entity`) or edit a record. Attributes the form doesn't show (aliases, action items…) are kept. */
export function EntityFormDialog({ kind, entity, initialName = "", onClose, onSaved }: {
  kind: EntityKind;
  entity?: Entity;
  initialName?: string;
  onClose: () => void;
  onSaved?: (e: Entity) => void;
}) {
  const { toast } = useShell();
  const [name, setName] = useState(entity?.name ?? initialName);
  const [summary, setSummary] = useState(entity?.summary ?? "");
  const [tags, setTags] = useState((entity?.tags ?? []).join(", "));
  const [occurred, setOccurred] = useState(toLocalInput(entity?.occurred_at ?? (kind === "meeting" ? new Date().toISOString() : null)));
  const [attrs, setAttrs] = useState<Record<string, string>>(() =>
    Object.fromEntries(ATTRIBUTE_FIELDS[kind].map((f) => [f.key, String(entity?.attributes?.[f.key] ?? "")])),
  );
  const [busy, setBusy] = useState(false);
  const isEvent = kind === "meeting" || kind === "document";

  const save = async () => {
    setBusy(true);
    try {
      const attributes: Record<string, unknown> = { ...(entity?.attributes ?? {}) };
      for (const [k, v] of Object.entries(attrs)) {
        if (v.trim()) attributes[k] = v.trim();
        else delete attributes[k];
      }
      const body = {
        name: name.trim(),
        summary: summary.trim() || null,
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
        attributes,
        ...(isEvent ? { occurred_at: occurred ? new Date(occurred).toISOString() : null } : {}),
      };
      const saved = entity ? await crmApi.updateEntity(entity.id, body) : await crmApi.createEntity({ kind, ...body });
      onSaved?.(saved);
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(false);
    }
  };

  return (
    <Dialog title={entity ? `Edit ${entity.name}` : `New ${KIND_LABEL[kind].one.toLowerCase()}`} onClose={onClose}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (name.trim()) void save(); }}>
        <Field label="Name">
          <input className="field h-10 w-full" value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
        </Field>
        {isEvent && (
          <Field label={kind === "meeting" ? "When" : "Date"}>
            <input type="datetime-local" className="field h-10 w-full" value={occurred} onChange={(e) => setOccurred(e.target.value)} />
          </Field>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          {ATTRIBUTE_FIELDS[kind].map((f) => (
            <Field key={f.key} label={f.label}>
              <input className="field h-10 w-full" type={f.type ?? "text"} value={attrs[f.key]} onChange={(e) => setAttrs((a) => ({ ...a, [f.key]: e.target.value }))} />
            </Field>
          ))}
        </div>
        <Field label={isEvent ? "Summary" : "About"}>
          <textarea className="field min-h-24 w-full" value={summary} onChange={(e) => setSummary(e.target.value)} />
        </Field>
        <Field label="Tags" hint="Separate with commas.">
          <input className="field h-10 w-full" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="investor, climate" />
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn btn-md btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-md btn-primary" disabled={!name.trim() || busy}>{entity ? "Save" : "Create"}</button>
        </div>
      </form>
    </Dialog>
  );
}

export function MergeDialog({ entity, onClose, onMerged }: { entity: Entity; onClose: () => void; onMerged: (kept: Entity) => void }) {
  const { toast } = useShell();
  const [target, setTarget] = useState<EntitySummary | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    if (!target) return;
    setBusy(true);
    try {
      onMerged(await crmApi.mergeEntity(entity.id, target.id));
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(false);
    }
  };
  return (
    <Dialog title={`Merge ${entity.name} into…`} onClose={onClose} width={480}>
      <p className="mb-4 text-label leading-relaxed text-ink-soft">
        Pick the record to keep. Relationships, notes and tags move over; {entity.name} is deleted and kept as an alternate name, so future notes match the record you keep.
      </p>
      {target ? (
        <div className="inset-surface flex items-center justify-between px-3.5 py-2.5 text-label">
          <span className="truncate font-medium">{target.name}{target.subtitle && <span className="font-normal text-ink-soft"> · {target.subtitle}</span>}</span>
          <button className="icon-btn" aria-label="Choose someone else" onClick={() => setTarget(null)}><CloseIcon size={16} /></button>
        </div>
      ) : (
        <EntityPicker kinds={[entity.kind]} exclude={[entity.id]} onSelect={setTarget} autoFocus placeholder={`Search ${KIND_LABEL[entity.kind].many.toLowerCase()}`} />
      )}
      <div className="mt-6 flex justify-end gap-2">
        <button className="btn btn-md btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-md btn-primary" disabled={!target || busy} onClick={() => void run()}>Merge</button>
      </div>
    </Dialog>
  );
}

interface RelOption { key: string; kind: string; direction: "out" | "in"; label: string; otherKinds: EntityKind[] | null }

/** Relationship kinds a record of `kind` can take part in, read from its own point of view. */
function relationshipOptions(kinds: Record<string, RelKindInfo> | undefined, kind: EntityKind): RelOption[] {
  if (!kinds) return [];
  const out: RelOption[] = [];
  for (const [k, r] of Object.entries(kinds)) {
    if (!r.sources || r.sources.includes(kind)) out.push({ key: `${k}:out`, kind: k, direction: "out", label: r.label, otherKinds: r.targets });
    if (!r.symmetric && (!r.targets || r.targets.includes(kind))) out.push({ key: `${k}:in`, kind: k, direction: "in", label: r.inverse, otherKinds: r.sources });
  }
  return out;
}

export function AddRelationship({ entity, onDone }: { entity: Entity; onDone: () => void }) {
  const { toast } = useShell();
  const { data: meta } = useLive(crmApi.meta);
  const options = relationshipOptions(meta?.relationship_kinds, entity.kind);
  const [key, setKey] = useState("");
  const [strength, setStrength] = useState(3);
  const [since, setSince] = useState("");
  const option = options.find((o) => o.key === key) ?? options[0];
  if (!option) return null;

  const create = async (other?: EntitySummary, name?: string) => {
    try {
      let otherId = other?.id;
      if (!otherId && name) otherId = (await crmApi.createEntity({ kind: option.otherKinds?.[0] ?? "person", name })).id;
      const [source_id, target_id] = option.direction === "out" ? [entity.id, otherId!] : [otherId!, entity.id];
      await crmApi.createRelationship({ source_id, target_id, kind: option.kind, strength, started_at: since || null });
      onDone();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <div className="inset-surface mb-4 space-y-3 p-4">
      <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
        <Field label={`${entity.name.split(" ")[0]}…`}>
          <Select label="Relationship" value={option.key} onChange={setKey} options={options.map((o) => ({ value: o.key, label: o.label }))} />
        </Field>
        <Field label="Since">
          <input type="date" className="field h-10 w-full" value={since} onChange={(e) => setSince(e.target.value)} />
        </Field>
      </div>
      <EntityPicker
        kinds={option.otherKinds ?? undefined}
        exclude={[entity.id]}
        placeholder={`Search ${option.otherKinds ? option.otherKinds.map((k) => KIND_LABEL[k].many.toLowerCase()).join(" or ") : "anything"}`}
        onSelect={(o) => void create(o)}
        onCreate={(n) => void create(undefined, n)}
      />
      <div className="flex items-center gap-2 text-hint text-ink-soft">
        Strength <StrengthDots value={strength} onChange={setStrength} />
      </div>
    </div>
  );
}
