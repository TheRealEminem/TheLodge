// Hats: the parts of your life (a company, a committee, personal). Wearing one shows that part of your book; "All hats"
// shows the whole of it. The server half is hats.py.
import { useEffect, useRef, useState } from "react";
import { ChevronDownIcon, CloseIcon, PencilIcon, PlusIcon, SearchIcon, TrashIcon } from "@core/components/icons";
import { PageHeader, Select, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { navigate } from "@core/router";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { EntitySummary, Facet, Hat } from "./api";
import { Dialog, EntityPicker, Field } from "./forms";

const MANAGE = "__manage";

/** In the sidebar: which hat you're wearing. */
export function HatSwitcher() {
  const { toast } = useShell();
  const { data } = useLive(crmApi.hats);
  if (!data) return null;
  const change = (v: string) => {
    if (v === MANAGE) navigate("crm/hats");
    else crmApi.wearHat(v || null).catch((e: Error) => toast(e.message, "error"));
  };
  return (
    <div className="px-3 pt-3">
      <Select
        label="Which hat you're wearing"
        size="sm"
        className="w-full"
        value={data.active ?? ""}
        onChange={change}
        options={[{ value: "", label: "All hats" }, ...data.hats.map((h) => ({ value: h.id, label: h.name })), { value: MANAGE, label: "Manage hats…" }]}
      />
    </div>
  );
}

function HatDialog({ hat, onClose }: { hat?: Hat; onClose: () => void }) {
  const { toast } = useShell();
  const [name, setName] = useState(hat?.name ?? "");
  const [title, setTitle] = useState(hat?.title ?? "");
  const [org, setOrg] = useState<{ id: string; name: string } | null>(hat?.org_id ? { id: hat.org_id, name: hat.org_name ?? "" } : null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const body = { name: name.trim(), title: title.trim() || null, org_id: org?.id ?? null };
      if (hat) await crmApi.changeHat(hat.id, body);
      else await crmApi.createHat(body);
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(false);
    }
  };
  return (
    <Dialog title={hat ? `Edit ${hat.name}` : "New hat"} onClose={onClose} width={480}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (name.trim()) void save(); }}>
        <Field label="Name"><input className="field h-10 w-full" value={name} onChange={(e) => setName(e.target.value)} autoFocus required /></Field>
        <Field label="What you are in it" hint="The AI reads what comes in under this hat knowing this.">
          <input className="field h-10 w-full" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Chair" />
        </Field>
        <div>
          <span className="mb-1 block text-ui font-medium">Where</span>
          {org ? (
            <div className="inset-surface flex items-center justify-between gap-3 px-3.5 py-2.5 text-ui">
              <span className="truncate font-medium">{org.name}</span>
              <button type="button" className="icon-btn h-7 w-7" aria-label="Choose another organization" onClick={() => setOrg(null)}><CloseIcon size={14} /></button>
            </div>
          ) : <EntityPicker kinds={["organization"]} onSelect={(e: EntitySummary) => setOrg({ id: e.id, name: e.name })} placeholder="Find the organization" />}
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn btn-md btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-md btn-primary" disabled={!name.trim() || busy}>{hat ? "Save" : "Create"}</button>
        </div>
      </form>
    </Dialog>
  );
}

export default function HatsPage() {
  const { toast, confirm } = useShell();
  const { data, error } = useLive(crmApi.hats);
  const [editing, setEditing] = useState<Hat | "new" | null>(null);
  const remove = async (h: Hat) => {
    if (!(await confirm({ title: `Delete ${h.name}?`, body: "Only the hat goes. Everyone and everything in it stays in your book.", confirmLabel: "Delete", tone: "danger" }))) return;
    crmApi.deleteHat(h.id).catch((e: Error) => toast(e.message, "error"));
  };
  return (
    <>
      <PageHeader
        title="Hats"
        subtitle="The parts of your life. Wear one and People, Organizations, Network and Home show only that part. Someone can be in more than one."
        actions={<button className="btn btn-md btn-primary" onClick={() => setEditing("new")}><PlusIcon size={18} /> New hat</button>}
      />
      <div className="animate-enter space-y-3" style={{ animationDelay: "60ms" }}>
        {error && <p className="text-ui text-trail-deep">{error}</p>}
        {!data && !error && <Skeleton className="h-40 w-full rounded-xl" />}
        {data && (
          <ul className="panel divide-y divide-line">
            {data.hats.length === 0 && <li className="px-5 py-4 text-ui text-ink-soft">No hats yet. Turn on Trailmix in Settings and its workspaces become hats, or make one here.</li>}
            {data.hats.map((h) => (
              <li key={h.id} className="group flex flex-wrap items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-label font-medium">{h.name}</span>
                    {data.active === h.id && <span className="chip bg-forest-soft text-forest-deep">wearing</span>}
                  </div>
                  <div className="truncate text-hint text-ink-soft">
                    {[[h.title, h.org_name].filter(Boolean).join(", "), `${h.people} people`, `${h.orgs} organizations`, `${h.events} meetings and documents`, h.workspace !== null && "follows its Trailmix workspace"].filter(Boolean).join(" · ")}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {data.active !== h.id && <button className="btn btn-sm btn-soft" onClick={() => void crmApi.wearHat(h.id)}>Wear it</button>}
                  <button className="icon-btn h-8 w-8" aria-label={`Edit ${h.name}`} onClick={() => setEditing(h)}><PencilIcon size={16} /></button>
                  <button className="icon-btn h-8 w-8" aria-label={`Delete ${h.name}`} onClick={() => void remove(h)}><TrashIcon size={16} /></button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {!!data?.unhatted && (
          <p className="text-hint text-ink-soft">
            <a className="underline" href="#/crm/people?nohat=1">{data.unhatted} {data.unhatted === 1 ? "person isn't" : "people aren't"} in any hat yet</a>: mostly people from documents and spreadsheets. They show under All hats until you put them in one.
          </p>
        )}
      </div>
      {editing && <HatDialog hat={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

/** On a record's page: which hats it's in. Click to put it in or take it out; that holds, whatever comes in later. */
export function HatChips({ entityId }: { entityId: string }) {
  const { toast } = useShell();
  const { data } = useLive(() => crmApi.hatsOf(entityId), [entityId]);
  if (!data?.length) return null;
  const toggle = (id: string, isIn: boolean) => crmApi.placeInHat(id, [entityId], isIn ? "no" : "you").catch((e: Error) => toast(e.message, "error"));
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1" role="group" aria-label="Hats">
      {data.map((h) => (
        <button key={h.id} className={h.in ? "chip bg-forest-soft text-forest-deep" : "chip bg-surface-subtle text-ink-faint hover:bg-forest/10"} aria-pressed={h.in}
          data-tip={h.in ? `Take out of ${h.name}` : `Put in ${h.name}`} onClick={() => void toggle(h.id, h.in)}>
          {h.name}
        </button>
      ))}
    </div>
  );
}

/** Beside a filtered list: put everyone in it in a hat. */
export function PutInHat({ count, ids }: { count: number; ids: () => Promise<string[]> }) {
  const { toast } = useShell();
  const { data } = useLive(crmApi.hats);
  if (!data?.hats.length || !count) return null;
  const put = async (hat: string) => {
    if (!hat) return;
    try {
      const all = await ids();
      await crmApi.placeInHat(hat, all, "you");
      toast(`${all.length} ${all.length === 1 ? "person" : "people"} put in ${data.hats.find((h) => h.id === hat)?.name}.`);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <Select label="Put everyone listed in a hat" size="sm" value="" onChange={(v) => void put(v)}
      options={[{ value: "", label: `Put these ${count} in a hat` }, ...data.hats.map((h) => ({ value: h.id, label: h.name }))]} />
  );
}

/** One way of narrowing a list (tag, organization, topic…), searchable, with how many each would leave. */
export function FacetPicker({ label, value, options, onChange }: { label: string; value?: string; options?: Facet[]; onChange: (v: string | null) => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  const chosen = options?.find((o) => o.id === value);
  if (value) {
    return (
      <button className="chip h-9 bg-forest-soft px-3 text-forest-deep" onClick={() => onChange(null)} aria-label={`Remove the ${label} filter`}>
        {label}: {chosen?.name ?? "…"} <CloseIcon size={12} />
      </button>
    );
  }
  if (options && options.length === 0) return null;
  const needle = q.trim().toLowerCase();
  const rows = (options ?? []).filter((o) => !needle || o.name.toLowerCase().includes(needle));
  return (
    <div ref={box} className="relative">
      <button className="btn btn-sm btn-soft" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {label} {options && <span className="tabular-nums text-ink-soft">{options.length}</span>} <ChevronDownIcon size={14} />
      </button>
      {open && (
        <div className="panel absolute left-0 z-30 mt-1 w-72 animate-pop p-1.5 shadow-lg">
          <div className="relative mb-1">
            <SearchIcon size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint" />
            <input className="field h-8 w-full pl-8" value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Find ${label.toLowerCase()}`} aria-label={`Find ${label.toLowerCase()}`} autoFocus
              onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }} />
          </div>
          <ul className="max-h-72 overflow-y-auto">
            {rows.map((o) => (
              <li key={o.id}>
                <button className="flex w-full items-baseline justify-between gap-3 rounded-sm px-2.5 py-1.5 text-left text-ui hover:bg-forest/[.07]" onClick={() => { setOpen(false); setQ(""); onChange(o.id); }}>
                  <span className="truncate">{o.name}</span>
                  <span className="shrink-0 tabular-nums text-ink-soft">{o.count}</span>
                </button>
              </li>
            ))}
            {rows.length === 0 && <li className="px-2.5 py-1.5 text-ui text-ink-soft">None match.</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
