// Sediment's pages: where you choose someone (with the latest readings and your products), and one person: their
// readings, their portrait and rehearsals (rehearse.tsx).
import { useEffect, useMemo, useState } from "react";
import { api } from "@core/api";
import type { PersonChoice } from "@core/api";
import { Empty, PersonPicker } from "@core/components/blocks";
import { BackIcon, LinesIcon, PencilIcon, PlusIcon, SearchIcon, TrashIcon } from "@core/components/icons";
import { PageHeader, Segmented, Skeleton, Spinner } from "@core/components/ui";
import { relativeTime } from "@core/format";
import { useLive } from "@core/live";
import type { RouteProps } from "@core/registry";
import { navigate, useQueryParams } from "@core/router";
import { useShell } from "@core/shell";
import { sedimentApi } from "./api";
import type { PersonPage, Reading, SavedSubject, Subject } from "./api";
import { Dialog, Field, Layers, ReadingView, STANCE, StanceChip, firstName } from "./bits";
import { PortraitPanel, RehearsePanel } from "./rehearse";

// ── Choosing someone ──────────────────────────────────────────────────

export function SedimentHome() {
  const { toast } = useShell();
  const { data: recent } = useLive(sedimentApi.recent);
  const [choice, setChoice] = useState<PersonChoice | null>(null);
  const open = (c: PersonChoice | null) => {
    setChoice(c);
    if (!c) return;
    if (!c.ref || c.ref === "core:me" || !c.ref.startsWith("crm:")) {
      toast("Choose someone from your book, other than you", "error");
      setChoice(null);
      return;
    }
    navigate(`sediment/${c.ref}`);
  };
  return (
    <>
      <PageHeader title="Sediment Analysis" subtitle="How the people you know seem to feel about you, your company, someone else or your product, read from what's on file about them." />
      <section className="panel mb-8 animate-enter p-5 sm:px-6">
        <p className="mb-2 text-ui font-medium">Whose feelings?</p>
        <PersonPicker value={choice} onChange={open} label="Choose someone" placeholder="Choose someone from your book" className="w-full sm:w-96" />
        <p className="mt-2 text-hint text-ink-soft">Or press Sediment on anyone's profile in People.</p>
      </section>

      <h2 className="mb-3 px-1 text-heading font-semibold tracking-[-0.01em]">Latest readings</h2>
      {!recent && <Skeleton className="h-24 w-full rounded-xl" />}
      {recent?.length === 0 && (
        <Empty icon={<LinesIcon size={20} />} title="No readings yet">
          Choose someone above and take a reading. It will appear here, with the ones after it.
        </Empty>
      )}
      {!!recent?.length && (
        <div className="panel animate-enter divide-y divide-line px-2">
          {recent.map((r) => (
            <a key={r.id} href={`#/sediment/${r.person_ref}?subject=${encodeURIComponent(r.subject_key)}`} className="flex items-center gap-3 rounded-md px-3 py-3 transition-colors hover:bg-forest/[.04]">
              <span className={`h-8 w-1.5 shrink-0 rounded-full ${STANCE[r.stance ?? "unknown"].band}`} aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-label font-medium">{r.person_name}</span>
                <span className="block truncate text-meta text-ink-soft">On {r.subject_key === "me" ? "you" : r.subject_name} · {relativeTime(r.read_at)}</span>
              </span>
              <StanceChip stance={r.stance} />
            </a>
          ))}
        </div>
      )}

      <Products />
    </>
  );
}

function Products() {
  const { toast, confirm } = useShell();
  const { data: subjects } = useLive(sedimentApi.subjects);
  const [editing, setEditing] = useState<SavedSubject | "new" | null>(null);
  const products = subjects?.filter((s) => s.kind === "product") ?? [];
  const remove = async (s: SavedSubject) => {
    if (!(await confirm({ title: `Delete ${s.name}?`, body: "It stops being offered as a subject. Readings already taken stay.", confirmLabel: "Delete", tone: "danger" }))) return;
    sedimentApi.removeSubject(s.id).catch((e: Error) => toast(e.message, "error"));
  };
  return (
    <section className="mt-10 animate-enter">
      <div className="mb-3 flex items-end justify-between gap-3 px-1">
        <div>
          <h2 className="text-heading font-semibold tracking-[-0.01em]">Your products</h2>
          <p className="mt-0.5 text-ui text-ink-soft">Described once here, so any reading can be about one.</p>
        </div>
        <button className="btn btn-sm btn-soft" onClick={() => setEditing("new")}><PlusIcon size={16} /> Add a product</button>
      </div>
      {subjects && products.length === 0 && <p className="inset-surface px-5 py-4 text-ui text-ink-soft">Products you add will appear here.</p>}
      {!!products.length && (
        <div className="panel divide-y divide-line px-5 sm:px-6">
          {products.map((s) => (
            <div key={s.id} className="flex items-start gap-3 py-3.5">
              <div className="min-w-0 flex-1">
                <p className="text-label font-medium">{s.name}</p>
                {s.description && <p className="mt-0.5 text-hint text-ink-soft">{s.description}</p>}
                {!!s.terms.length && <p className="mt-0.5 text-meta text-ink-soft">Also called {s.terms.join(", ")}</p>}
              </div>
              <button className="icon-btn" aria-label={`Edit ${s.name}`} data-tip="Edit" onClick={() => setEditing(s)}><PencilIcon size={16} /></button>
              <button className="icon-btn hover:!bg-trail-soft hover:!text-trail-deep" aria-label={`Delete ${s.name}`} data-tip="Delete" onClick={() => void remove(s)}><TrashIcon size={16} /></button>
            </div>
          ))}
        </div>
      )}
      {editing && <ProductDialog product={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </section>
  );
}

const splitTerms = (text: string) => text.split(",").map((t) => t.trim()).filter(Boolean);

function ProductDialog({ product, onClose, onSaved }: { product: SavedSubject | null; onClose: () => void; onSaved?: (s: SavedSubject) => void }) {
  const { toast } = useShell();
  const [name, setName] = useState(product?.name ?? "");
  const [description, setDescription] = useState(product?.description ?? "");
  const [terms, setTerms] = useState(product?.terms.join(", ") ?? "");
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      const s = product
        ? await sedimentApi.editSubject(product.id, name, description, splitTerms(terms))
        : await sedimentApi.addProduct(name, description, splitTerms(terms));
      onSaved?.(s);
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog title={product ? `Edit ${product.name}` : "Add a product"} onClose={onClose}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <ProductFields name={name} setName={setName} description={description} setDescription={setDescription} terms={terms} setTerms={setTerms} />
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn btn-md btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-md btn-primary" disabled={!name.trim() || saving}>{saving && <Spinner />} {product ? "Save" : "Add"}</button>
        </div>
      </form>
    </Dialog>
  );
}

function ProductFields({ name, setName, description, setDescription, terms, setTerms }: {
  name: string; setName: (v: string) => void; description: string; setDescription: (v: string) => void; terms: string; setTerms: (v: string) => void;
}) {
  return (
    <>
      <Field label="Name">
        <input className="field h-10 w-full" value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="Coldbox" />
      </Field>
      <Field label="What it is" hint="A line or two, so the AI knows what it's reading about.">
        <textarea className="field block min-h-[72px] w-full resize-y py-2" value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <Field label="Other names it goes by" hint="Separated by commas: earlier names, short forms, how people write it in notes.">
        <input className="field h-10 w-full" value={terms} onChange={(e) => setTerms(e.target.value)} placeholder="Cold box, CB" />
      </Field>
    </>
  );
}

/** Add a subject: a product, or someone or something from your book. */
function SubjectDialog({ onClose, onAdded }: { onClose: () => void; onAdded: (s: SavedSubject) => void }) {
  const { toast } = useShell();
  const [mode, setMode] = useState<"book" | "product">("book");
  const [q, setQ] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [terms, setTerms] = useState("");
  const [hits, setHits] = useState<{ ref: string; title: string; kind: "person" | "organization" }[] | null>(null);
  useEffect(() => {
    if (mode !== "book" || !q.trim()) {
      setHits(null);
      return;
    }
    let alive = true;
    const t = setTimeout(() => {
      api.search(q.trim()).then((groups) => {
        if (!alive) return;
        const crm = groups.find((g) => g.module === "crm")?.hits ?? [];
        setHits(crm.filter((h) => h.snippet === "Person" || h.snippet === "Organization")
          .map((h) => ({ ref: h.ref, title: h.title, kind: h.snippet === "Person" ? "person" : "organization" })));
      }, () => alive && setHits([]));
    }, 180);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [q, mode]);
  const add = async (fn: () => Promise<SavedSubject>) => {
    try {
      onAdded(await fn());
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <Dialog title="Add a subject" onClose={onClose}>
      <div className="mb-4">
        <Segmented<"book" | "product"> label="What kind" value={mode} onChange={setMode} options={[{ id: "book", label: "From your book" }, { id: "product", label: "A product" }]} />
      </div>
      {mode === "book" ? (
        <>
          <label className="relative block">
            <SearchIcon size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-soft" />
            <input className="field h-10 w-full pl-9" autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="A person or an organization" aria-label="Search your book" />
          </label>
          <div className="mt-2 max-h-72 overflow-y-auto">
            {hits?.length === 0 && <p className="px-1 py-3 text-ui text-ink-soft">Nobody and nothing in your book by that name.</p>}
            {hits?.map((h) => (
              <button key={h.ref} className="flex w-full items-center justify-between gap-3 rounded-md px-3 py-2.5 text-left transition-colors hover:bg-forest/[.05]" onClick={() => void add(() => sedimentApi.addFromBook(h.ref, h.kind))}>
                <span className="truncate text-label font-medium">{h.title}</span>
                <span className="shrink-0 text-meta text-ink-soft">{h.kind === "person" ? "Person" : "Organization"}</span>
              </button>
            ))}
          </div>
        </>
      ) : (
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void add(() => sedimentApi.addProduct(name, description, splitTerms(terms))); }}>
          <ProductFields name={name} setName={setName} description={description} setDescription={setDescription} terms={terms} setTerms={setTerms} />
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn btn-md btn-ghost" onClick={onClose}>Cancel</button>
            <button className="btn btn-md btn-primary" disabled={!name.trim()}>Add</button>
          </div>
        </form>
      )}
    </Dialog>
  );
}

// ── One person ────────────────────────────────────────────────────────

export function SedimentPerson({ params }: RouteProps) {
  const ref = params.ref;
  const { data, error } = useLive(() => sedimentApi.person(ref), [ref]);
  useEffect(() => {
    if (data && !data.missing && data.person.ref !== ref) navigate(`sediment/${data.person.ref}`);   // merged since
  }, [data, ref]);
  return (
    <div className="animate-enter">
      <a href="#/sediment" className="btn btn-sm btn-ghost -ml-3 mb-3"><BackIcon size={16} /> Sediment</a>
      {error ? <p className="inset-surface px-5 py-4 text-ui text-ink-soft">{error}</p>
        : !data ? <Skeleton className="h-40 w-full rounded-xl" />
        : data.missing ? <Missing page={data} />
        : <Person page={data} />}
    </div>
  );
}

function Missing({ page }: { page: PersonPage }) {
  const { toast, confirm } = useShell();
  const forget = async () => {
    if (!(await confirm({ title: "Delete their readings?", body: "Every reading of them is deleted.", confirmLabel: "Delete", tone: "danger" }))) return;
    sedimentApi.forget(page.person.ref).then(() => navigate("sediment"), (e: Error) => toast(e.message, "error"));
  };
  return (
    <div className="inset-surface px-5 py-4">
      <p className="text-ui">{page.person.name ?? "This person"} is no longer in your book, so there's nothing new to read.</p>
      {page.readings.length > 0 && <button className="btn btn-sm btn-soft mt-3" onClick={() => void forget()}><TrashIcon size={16} /> Delete their readings</button>}
    </div>
  );
}

function SubjectChip({ s, chosen, last, onPick }: { s: Subject; chosen: boolean; last?: Reading; onPick: () => void }) {
  return (
    <button
      className={`chip h-8 gap-2 px-3 transition-colors duration-150 ${chosen ? "bg-forest text-surface" : "bg-surface-subtle text-ink-soft hover:bg-forest/10 hover:text-ink"}`}
      aria-pressed={chosen}
      onClick={onPick}
    >
      {last?.stance && <span className={`h-2 w-2 rounded-full ${STANCE[last.stance].band} ${chosen ? "ring-1 ring-surface" : ""}`} aria-hidden />}
      {s.kind === "company" ? `Your company · ${s.name}` : s.name}
    </button>
  );
}

type Tab = "readings" | "portrait" | "rehearse";

/** One person: readings of how they feel, their portrait, and rehearsals. The tab and subject are kept in the address. */
function Person({ page }: { page: PersonPage }) {
  const { person } = page;
  const first = page.person.first ?? firstName(person.name ?? "");
  const [query, setQuery] = useQueryParams();
  const tab = (["readings", "portrait", "rehearse"].includes(query.get("tab") ?? "") ? query.get("tab") : "readings") as Tab;
  return (
    <>
      <header className="mb-5">
        <h1 className="page-title">{person.name}</h1>
        <p className="mt-1.5 text-body leading-relaxed text-ink-soft">
          How {first} seems to feel, and {first} as a whole, read from what's on file. <a href={`#/crm/e/${person.ref.replace(/^crm:/, "")}`} className="font-medium text-forest-deep hover:underline">Their profile</a>
        </p>
      </header>
      <div className="mb-4">
        <Segmented<Tab> kind="tab" label="Sediment" value={tab} onChange={(t) => setQuery({ tab: t === "readings" ? null : t })}
          options={[{ id: "readings", label: "Readings" }, { id: "portrait", label: "Portrait" }, { id: "rehearse", label: "Rehearse" }]} />
      </div>
      {tab === "readings" ? <Readings page={page} first={first} />
        : tab === "portrait" ? <PortraitPanel personRef={person.ref} first={first} />
        : <RehearsePanel personRef={person.ref} first={first} />}
    </>
  );
}

function Readings({ page, first }: { page: PersonPage; first: string }) {
  const { toast } = useShell();
  const { person, subjects, readings, provider } = page;
  const [query, setQuery] = useQueryParams();   // the subject is kept in the address, so a link can open it
  const key = query.get("subject") || "me";
  const [active, setActive] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [asking, setAsking] = useState(false);
  const [unchanged, setUnchanged] = useState<string | null>(null);
  const subject = subjects.find((s) => s.key === key) ?? subjects[0];
  const these = useMemo(() => readings.filter((r) => r.subject_key === key), [readings, key]);
  const shown = these.find((r) => r.id === active) ?? these[0];
  const lastOf = (k: string) => readings.find((r) => r.subject_key === k && r.status === "done");
  const busy = these.some((r) => r.status === "queued");

  const pick = (k: string) => {
    setQuery({ subject: k === "me" ? null : k });
    setActive(null);
    setUnchanged(null);
  };
  const take = async (again = false) => {
    setAsking(true);
    try {
      const out = await sedimentApi.take(person.ref, key, again);
      setUnchanged(out.unchanged ? out.since : null);
      setActive(out.reading.id);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setAsking(false);
    }
  };

  return (
    <>
      <section className="panel animate-enter p-5 sm:px-6">
        <p className="mb-2.5 text-ui font-medium">About what?</p>
        <div className="flex flex-wrap gap-1.5">
          {subjects.map((s) => <SubjectChip key={s.key} s={s} chosen={s.key === key} last={lastOf(s.key)} onPick={() => pick(s.key)} />)}
          <button className="chip h-8 gap-1.5 bg-surface-subtle px-3 text-ink-soft transition-colors hover:bg-forest/10 hover:text-ink" onClick={() => setAdding(true)}>
            <PlusIcon size={14} /> Add a subject
          </button>
        </div>

        {!provider.ready ? (
          <p className="mt-4 text-ui text-ink-soft">
            {provider.reason || "No AI is set up for this yet"}. Choose one under <a href="#/settings" className="font-medium text-forest-deep hover:underline">Settings → AI</a> to take readings.
          </p>
        ) : (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button className="btn btn-md btn-primary" disabled={asking || busy} onClick={() => void take()}>
              {asking ? <Spinner /> : <LinesIcon size={16} />} Take a reading
            </button>
            <p className="min-w-[14rem] flex-1 text-meta text-ink-soft">
              {subject?.key === "me" ? `How ${first} seems to feel about you` : `How ${first} seems to feel about ${subject?.name}`}, from what's on file, using {provider.label}{provider.local ? " on this Mac" : ""}.
              {page.transcripts ? " Meeting transcripts are included." : ""}
            </p>
          </div>
        )}
        {unchanged && (
          <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-ui text-ink-soft">
            Nothing new on file since the last reading, {relativeTime(unchanged)}.
            <button className="btn btn-sm btn-ghost" disabled={asking} onClick={() => void take(true)}>Read again anyway</button>
          </p>
        )}
        {person.material === false && <p className="mt-3 text-hint text-ink-soft">Not much on file about {first} yet, so a reading can't say much. Notes and meetings help most.</p>}
      </section>

      <section className="panel mt-4 animate-enter p-5 sm:px-6" style={{ animationDelay: "60ms" }}>
        {shown ? (
          <>
            <ReadingView reading={shown} first={first} provider={provider.label} />
            <Layers readings={these} active={shown.id} onPick={(id) => { setActive(id); setUnchanged(null); }} />
          </>
        ) : (
          <p className="text-ui text-ink-soft">No reading of this yet. Take one, and it will appear here, with the ones after it as layers.</p>
        )}
      </section>

      <p className="mt-4 px-1 text-meta text-ink-soft">A reading is the AI's judgement of your records, not something {first} said. Nothing here is added to their profile.</p>

      {adding && <SubjectDialog onClose={() => setAdding(false)} onAdded={(s) => pick(s.key)} />}
    </>
  );
}
