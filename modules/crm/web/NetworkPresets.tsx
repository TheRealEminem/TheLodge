// The questions the network answers: ready-made presets (who you know at…, who could introduce you to…), the
// ones you saved, and lists the AI writes from what you ask for. A preset's answer is a list of people with the
// reasons beside each name, drawn on the canvas as one more group.
import { useMemo, useState } from "react";
import { CloseIcon, SearchIcon, SparkleIcon, TrashIcon } from "@core/components/icons";
import { Select, Skeleton, Spinner, useConfirm } from "@core/components/ui";
import { useLive } from "@core/live";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { PresetAsk, PresetChoices, PresetIdea, PresetKind, PresetResult, PresetSpec, SavedPreset } from "./api";
import { Dialog, EntityPicker } from "./forms";
import { GROUP_META, GroupGlyph } from "./groups";
import { TierBadge } from "./tier";

type Needs = "group" | "target" | "event" | "two";

export const BUILT_IN: { kind: PresetKind; label: string; hint: string; needs?: Needs }[] = [
  { kind: "at", label: "Who you know at…", hint: "Everyone linked to an organization, topic or tag, the people you know best first", needs: "group" },
  { kind: "intro", label: "Who could introduce you to…", hint: "People you know who know a person, or someone at an organization", needs: "target" },
  { kind: "investors", label: "Investors and advisors", hint: "From your tags, the ties you recorded and their titles" },
  { kind: "event", label: "Everyone from an event…", hint: "Everyone at a meeting or a series of them, and anyone tagged with it", needs: "event" },
  { kind: "bridges", label: "In two groups at once…", hint: "The people who connect two groups", needs: "two" },
  { kind: "followups", label: "Follow-ups waiting", hint: "Prospects, leads and thank-yous you haven't met or rated yet" },
];

export interface ActivePreset {
  spec: PresetSpec;
  savedId?: string;
}

export function PresetBar({ onRun, asking, onAsk }: {
  onRun: (p: ActivePreset) => void;
  asking: boolean;
  onAsk: () => void;
}) {
  const [setup, setSetup] = useState<(typeof BUILT_IN)[number] | null>(null);
  const { data: saved } = useLive<SavedPreset[]>(crmApi.presets);
  return (
    <div className="mb-3 flex animate-enter flex-wrap items-center gap-1.5">
      <span className="mr-1 text-ui font-medium">Ask the network</span>
      {BUILT_IN.map((p) => (
        <button
          key={p.kind}
          className="chip h-7 bg-surface-subtle px-2.5 text-ink hover:bg-forest/[.08]"
          data-tip={p.hint}
          onClick={() => (p.needs ? setSetup(p) : onRun({ spec: { kind: p.kind } }))}
        >
          {p.label}
        </button>
      ))}
      <button aria-pressed={asking} onClick={onAsk} className={`chip h-7 gap-1 px-2.5 ${asking ? "bg-forest-soft text-forest-deep" : "bg-surface-subtle text-ink hover:bg-forest/[.08]"}`}>
        <SparkleIcon size={14} /> Ask for a list…
      </button>
      {(saved?.length ?? 0) > 0 && (
        <Select
          label="Saved presets"
          size="sm"
          className="w-44"
          value=""
          options={[{ value: "", label: "Saved presets" }, ...(saved ?? []).map((p) => ({ value: p.id, label: p.name, hint: p.about || undefined }))]}
          onChange={(id) => { const p = saved?.find((x) => x.id === id); if (p) onRun({ spec: p.spec, savedId: p.id }); }}
        />
      )}
      {setup && <PresetSetup preset={setup} onClose={() => setSetup(null)} onRun={(spec) => { setSetup(null); onRun({ spec }); }} />}
    </div>
  );
}

/** A searchable list of groups or meetings to pick from. */
function ChoiceList<T extends { id: string; name: string }>({ items, label, meta, glyph, onPick }: {
  items: T[];
  label: string;
  meta: (x: T) => string;
  glyph?: (x: T) => React.ReactNode;
  onPick: (x: T) => void;
}) {
  const [q, setQ] = useState("");
  const found = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return items.filter((x) => !needle || x.name.toLowerCase().includes(needle)).slice(0, 60);
  }, [items, q]);
  return (
    <div>
      <div className="relative">
        <SearchIcon size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
        <input
          className="field w-full pl-9"
          autoFocus
          placeholder={label}
          aria-label={label}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && found[0]) { e.preventDefault(); onPick(found[0]); } }}
        />
      </div>
      <ul className="mt-2 max-h-72 overflow-y-auto">
        {found.map((x) => (
          <li key={x.id}>
            <button className="flex w-full items-center gap-2 rounded-sm px-2.5 py-2 text-left text-ui hover:bg-forest/[.07] focus-visible:bg-forest/[.07]" onClick={() => onPick(x)}>
              {glyph?.(x)}
              <span className="truncate font-medium">{x.name}</span>
              <span className="ml-auto shrink-0 text-meta text-ink-soft">{meta(x)}</span>
            </button>
          </li>
        ))}
        {found.length === 0 && <li className="px-2.5 py-2 text-ui text-ink-soft">Nothing by that name.</li>}
      </ul>
    </div>
  );
}

type GroupChoice = PresetChoices["groups"][number];

function PresetSetup({ preset, onClose, onRun }: { preset: (typeof BUILT_IN)[number]; onClose: () => void; onRun: (spec: PresetSpec) => void }) {
  const { data: choices } = useLive(crmApi.presetChoices);
  const [first, setFirst] = useState<GroupChoice | null>(null);
  const groupList = (onPick: (g: GroupChoice) => void, label: string, without?: string) => (
    <ChoiceList
      items={(choices?.groups ?? []).filter((g) => g.id !== without)}
      label={label}
      glyph={(g) => <GroupGlyph kind={g.kind} className="text-forest" />}
      meta={(g) => `${GROUP_META[g.kind].one.toLowerCase()} · ${g.size}`}
      onPick={onPick}
    />
  );
  return (
    <Dialog title={preset.label.replace("…", "")} onClose={onClose} width={460}>
      <p className="mb-3 text-ui text-ink-soft">{preset.hint}.</p>
      {preset.needs !== "target" && !choices ? (
        <Skeleton className="h-40 w-full rounded-lg" />
      ) : preset.needs === "group" ? (
        groupList((g) => onRun({ kind: "at", group: g.id }), "Find an organization, topic or tag…")
      ) : preset.needs === "target" ? (
        <div className="min-h-[19rem]">{/* room for the picker's list, which opens below it */}
          <EntityPicker kinds={["person", "organization"]} placeholder="Find a person or organization…" autoFocus onSelect={(e) => onRun({ kind: "intro", target: e.id })} />
        </div>
      ) : preset.needs === "event" ? (
        <ChoiceList
          items={choices?.events ?? []}
          label="Find a meeting or event…"
          meta={(e) => `${e.at ? e.at.slice(0, 10) : e.kind} · ${e.size}`}
          onPick={(e) => onRun({ kind: "event", event: e.id })}
        />
      ) : first ? (
        <>
          <p className="mb-2 flex items-center gap-2 text-ui">
            <span className="text-ink-soft">First:</span> <GroupGlyph kind={first.kind} className="text-forest" /> <span className="font-medium">{first.name}</span>
            <button className="btn btn-sm btn-ghost ml-auto" onClick={() => setFirst(null)}>Change</button>
          </p>
          {groupList((g) => onRun({ kind: "bridges", a: first.id, b: g.id }), "Now the second group…", first.id)}
        </>
      ) : (
        groupList(setFirst, "Find the first group…")
      )}
    </Dialog>
  );
}

// ── What a preset found ───────────────────────────────────────────────

function SaveDialog({ title, about, spec, onClose }: { title: string; about: string; spec: PresetSpec; onClose: () => void }) {
  const { toast } = useShell();
  const [name, setName] = useState(title);
  const save = async () => {
    try {
      const saved = await crmApi.savePreset({ name: name.trim(), about, spec });
      toast(`Saved “${saved.name}”`, "success");
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <Dialog title="Save this preset" onClose={onClose} width={420}>
      <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) void save(); }} className="space-y-4">
        <p className="text-ui text-ink-soft">It's worked out again each time you open it, so it keeps up as your book grows.</p>
        <input className="field w-full" autoFocus value={name} onChange={(e) => setName(e.target.value)} aria-label="Preset name" maxLength={80} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-soft" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!name.trim()}>Save</button>
        </div>
      </form>
    </Dialog>
  );
}

export function PresetPanel({ result, error, savedId, onClose, onSelect, onPickAll }: {
  result: PresetResult | null | undefined;
  error?: string | null;
  savedId?: string;
  onClose: () => void;
  onSelect: (id: string) => void;
  onPickAll: (ids: string[]) => void;
}) {
  const { toast } = useShell();
  const [saving, setSaving] = useState(false);
  const [confirm, confirmDialog] = useConfirm();
  const remove = async () => {
    if (!savedId || !(await confirm({ title: `Delete “${result?.title}”?`, body: "Only the saved preset goes; nobody in it is touched.", confirmLabel: "Delete", tone: "danger" }))) return;
    await crmApi.deletePreset(savedId).catch((e) => toast((e as Error).message, "error"));
    onClose();
  };
  return (
    <section className="panel p-4">
      <div className="flex items-start gap-3">
        <span className="well well-forest"><GroupGlyph kind="preset" size={16} /></span>
        <div className="min-w-0 flex-1">
          <h2 className="text-label font-semibold">{result?.title ?? (error ? "That preset didn't run" : "Working it out…")}</h2>
          {result && <div className="text-meta text-ink-soft">{result.people.length} {result.people.length === 1 ? "person" : "people"}{result.about ? ` · ${result.about}` : ""}</div>}
        </div>
        <button className="icon-btn" aria-label="Close preset" onClick={onClose}><CloseIcon size={16} /></button>
      </div>
      {error && <p className="mt-3 text-ui text-trail-deep">{error}</p>}
      {result && (
        <>
          <div className="mt-3 flex flex-wrap gap-2">
            {!savedId && <button className="btn btn-sm btn-soft" onClick={() => setSaving(true)}>Save preset</button>}
            {result.people.length > 0 && <button className="btn btn-sm btn-ghost" onClick={() => onPickAll(result.people.map((p) => p.id))}>Pick everyone</button>}
            {savedId && <button className="btn btn-sm btn-danger-ghost" onClick={() => void remove()}><TrashIcon size={16} /> Delete preset</button>}
          </div>
          <div className="mt-3 border-t border-line pt-2">
            {result.people.length === 0 ? (
              <p className="py-2 text-ui text-ink-soft">Nobody in your book fits this yet.</p>
            ) : (
              <ul className="max-h-[26rem] space-y-2 overflow-y-auto">
                {result.people.map((p) => (
                  <li key={p.id} className="text-ui">
                    <div className="flex items-center gap-2">
                      <button className="truncate text-left font-medium hover:underline" onClick={() => onSelect(p.id)}>{p.name}</button>
                      {p.tier && <span className="ml-auto"><TierBadge tier={p.tier} /></span>}
                    </div>
                    <div className="text-meta text-ink-soft">{p.why.join(" · ")}</div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
      {!result && !error && <Skeleton className="mt-3 h-24 w-full rounded-lg" />}
      {saving && result && <SaveDialog title={result.title} about={result.about} spec={result.spec} onClose={() => setSaving(false)} />}
      {confirmDialog}
    </section>
  );
}

// ── Lists the AI writes ───────────────────────────────────────────────

function IdeaCard({ idea, onShow }: { idea: PresetIdea; onShow: () => void }) {
  const [saving, setSaving] = useState(false);
  return (
    <div className="inset-surface p-3">
      <div className="text-label font-medium">{idea.name}</div>
      {idea.about && <p className="text-hint text-ink-soft">{idea.about}</p>}
      <p className="mt-1 text-meta text-ink-soft">{idea.count} {idea.count === 1 ? "person" : "people"}: {idea.sample.join(", ")}{idea.count > idea.sample.length ? "…" : ""}</p>
      <div className="mt-2 flex gap-2">
        <button className="btn btn-sm btn-soft" onClick={onShow}>Show</button>
        <button className="btn btn-sm btn-ghost" onClick={() => setSaving(true)}>Save</button>
      </div>
      {saving && <SaveDialog title={idea.name} about={idea.about} spec={idea.spec} onClose={() => setSaving(false)} />}
    </div>
  );
}

function AskResult({ ask, onShow, onRetry }: { ask: PresetAsk; onShow: (spec: PresetSpec) => void; onRetry: () => void }) {
  return (
    <div className="mt-4 border-t border-line pt-3">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1 text-label font-medium">{ask.request ? `“${ask.request}”` : "Lists worth having"}</div>
        <button className="icon-btn !h-7 !w-7" aria-label="Dismiss" onClick={() => void crmApi.dismissAsk(ask.id)}><CloseIcon size={14} /></button>
      </div>
      {ask.status === "queued" && <p className="mt-1 flex items-center gap-2 text-ui text-ink-soft"><Spinner className="text-sky" /> Reading your book…</p>}
      {ask.status === "error" && (
        <div className="mt-2 rounded-lg border border-trail/20 bg-trail-soft/70 p-3 text-ui text-trail-deep">
          <div className="font-semibold">The list didn't come through.</div>
          <div>{ask.error}</div>
          <button className="btn btn-sm btn-soft mt-2" onClick={onRetry}>Try again</button>
        </div>
      )}
      {ask.status === "done" && ask.ideas.length === 0 && <p className="mt-1 text-ui text-ink-soft">Nothing in your book fits that yet.</p>}
      {ask.status === "done" && ask.ideas.length > 0 && (
        <div className="mt-2 space-y-2">
          {ask.ideas.map((idea, i) => <IdeaCard key={i} idea={idea} onShow={() => onShow(idea.spec)} />)}
          {ask.written_by && <p className="text-meta text-ink-soft">Written by {ask.written_by}</p>}
        </div>
      )}
    </div>
  );
}

export function AskPanel({ onShow, onClose }: { onShow: (spec: PresetSpec) => void; onClose: () => void }) {
  const { toast } = useShell();
  const { data: asks } = useLive<PresetAsk[]>(crmApi.presetAsks);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async (request: string, replaces?: string) => {
    setBusy(true);
    try {
      await crmApi.askForPresets(request);
      if (replaces) await crmApi.dismissAsk(replaces);
      setText("");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel p-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 text-heading font-semibold"><SparkleIcon size={16} /> Ask for a list</h2>
        <button className="icon-btn" aria-label="Close" onClick={onClose}><CloseIcon size={16} /></button>
      </div>
      <p className="mt-1 text-hint text-ink-soft">Say who you're looking for. The AI reads your tags, organizations, meetings and summaries and writes a list you can keep.</p>
      <form className="mt-3 space-y-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) void send(text.trim()); }}>
        <textarea
          className="field w-full resize-none"
          rows={2}
          maxLength={500}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && text.trim()) { e.preventDefault(); void send(text.trim()); } }}
          placeholder="Everyone who could help with cold-chain funding"
          aria-label="Who are you looking for?"
        />
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-sm btn-primary" disabled={busy || !text.trim()}>Write the list</button>
          <button type="button" className="btn btn-sm btn-soft" disabled={busy} onClick={() => void send("")} data-tip="The AI looks through your book and suggests lists worth having">Suggest some</button>
        </div>
      </form>
      {(asks ?? []).map((a) => <AskResult key={a.id} ask={a} onShow={onShow} onRetry={() => void send(a.request, a.id)} />)}
    </section>
  );
}
