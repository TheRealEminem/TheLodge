// People with nothing on file: the flag, the brief for a deep-research tool, and bringing the report back.
import { useRef, useState } from "react";
import { CheckIcon, ClockIcon, CopyIcon, DocIcon, PlusIcon, SearchIcon, SparkleIcon } from "@core/components/icons";
import { useLive } from "@core/live";
import { navigate } from "@core/router";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { Entity } from "./api";
import { Dialog } from "./forms";
import { formatDate } from "./format";
import { GeminiDialog, GeminiRunLine } from "./GeminiResearch";

export const NEEDS_RESEARCH_CHIP = "chip bg-sun-soft text-sun-deep";

/** Copies the brief in one click. WebKit only allows a copy that starts inside the click, so the text is handed over
 *  as a promise; if even that is refused, the caller shows the text instead. */
async function copyBrief(personId: string): Promise<string | null> {
  const text = crmApi.researchBrief(personId).then((r) => r.text);
  try {
    await navigator.clipboard.write([new ClipboardItem({ "text/plain": text.then((t) => new Blob([t], { type: "text/plain" })) })]);
    return null;
  } catch {
    return text;
  }
}

function BriefDialog({ text, onClose }: { text: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Dialog title="Research brief" onClose={onClose} width={640}>
      <p className="text-ui text-ink-soft">Paste this into Gemini Deep Research (or another deep-research tool). Nothing is sent from here. The report keeps a ref, so when you add it back, even in a folder of reports, it finds this person by itself.</p>
      <textarea className="field mt-3 h-72 w-full resize-none p-3 text-ui" readOnly aria-label="Research brief" value={text} onFocus={(e) => e.currentTarget.select()} />
      <div className="mt-4 flex justify-end gap-2">
        <button className="btn btn-md btn-ghost" onClick={onClose}>Close</button>
        <button className="btn btn-md btn-primary" onClick={() => void navigator.clipboard.writeText(text).then(() => setCopied(true)).catch(() => undefined)}>
          {copied ? <CheckIcon size={18} /> : <CopyIcon size={18} />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </Dialog>
  );
}

/** Paste the report, or choose the file the tool gave you. It's read like any other profile, then waits for you. */
function AddResearchDialog({ person, onClose }: { person: Entity; onClose: () => void }) {
  const { toast } = useShell();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  const send = async (go: () => Promise<{ id: string } | { id: string }[]>) => {
    setBusy(true);
    try {
      const res = await go();
      const id = Array.isArray(res) ? res[0]?.id : res.id;
      toast(`Reading the research on ${person.name}. It will wait for your OK.`);
      onClose();
      navigate(id ? `crm/inbox/${id}` : "crm/inbox");
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(false);
    }
  };

  return (
    <Dialog title={`Add the research on ${person.name}`} onClose={onClose} width={640}>
      <p className="text-ui text-ink-soft">
        Paste the report from your deep-research tool, or choose its file. From Gemini, use Export to Docs, then in Google
        Docs File → Download → .docx or .md. The summary and facts are added to {person.name}, and the whole report is
        kept as a note. You check it before anything is saved.
      </p>
      <textarea className="field mt-3 h-64 w-full resize-none p-3 text-ui" placeholder="Paste the report here" aria-label="Research report" value={text} onChange={(e) => setText(e.target.value)} />
      <input ref={file} type="file" className="hidden" aria-label="Choose a research file" accept=".pdf,.docx,.md,.txt,.markdown,.odt,.rtf,.html,.htm"
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void send(() => crmApi.addFiles([{ file: f, path: f.name }], false, person.id)); }} />
      <div className="mt-4 flex flex-wrap justify-between gap-2">
        <button className="btn btn-md btn-soft" disabled={busy} onClick={() => file.current?.click()}><DocIcon size={18} /> Choose a file</button>
        <div className="flex gap-2">
          <button className="btn btn-md btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-md btn-primary" disabled={busy || text.trim().length < 40}
            onClick={() => void send(() => crmApi.addNotes({ text: text.trim(), subject_id: person.id }))}>
            <PlusIcon size={18} /> Add research
          </button>
        </div>
      </div>
    </Dialog>
  );
}

/** On a person's page: what to do about missing research, or what you decided. Shows nothing once they have some. */
export function ResearchCard({ person }: { person: Entity }) {
  const { toast } = useShell();
  const { data } = useLive(() => crmApi.researchStatus(person.id), [person.id]);
  const [adding, setAdding] = useState(false);
  const [shown, setShown] = useState<string | null>(null);
  const [gemini, setGemini] = useState(false);
  if (!data) return null;
  if (data.state === "has_context") return <GeminiRunLine person={person} offerMore />;

  const act = async (action: "snooze" | "dismiss" | "restore") => {
    try {
      await crmApi.setResearch(person.id, action);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const copy = async () => {
    try {
      const fallback = await copyBrief(person.id);
      if (fallback === null) toast("Brief copied. Paste it into Gemini Deep Research.");
      else setShown(await fallback);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const first = person.name.split(" ")[0];

  if (data.state === "name_needed") {
    return <p className="inset-surface px-5 py-3.5 text-ui text-ink-soft">Nothing on file about {first} yet. Add a surname first: a first name alone would find the wrong person.</p>;
  }
  if (data.state !== "needed") {
    const when = data.until ? formatDate(data.until, { year: undefined }) : null;
    return (
      <div className="inset-surface flex flex-wrap items-center gap-3 px-5 py-3">
        <ClockIcon size={16} className="shrink-0 text-ink-faint" />
        <p className="min-w-0 flex-1 text-ui text-ink-soft">
          {data.state === "snoozed" ? `Research on ${first} is snoozed${when ? ` until ${when}` : ""}.` : `You marked ${first} as not worth researching.`}
        </p>
        <button className="btn btn-sm btn-ghost" onClick={() => void act("restore")}>Bring it back</button>
      </div>
    );
  }
  return (
    <>
      <section className="panel flex flex-wrap items-center gap-x-4 gap-y-3 p-4">
        <span className="well"><SearchIcon size={16} /></span>
        <div className="min-w-52 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-label font-medium">Nothing on file about {first}</h2>
            <span className={NEEDS_RESEARCH_CHIP}>needs research</span>
          </div>
          <p className="mt-0.5 text-hint text-ink-soft">Have The Lodge research them with Gemini, or copy the brief into Gemini Deep Research and bring the report back here (or drop it in the Inbox with any others).</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-sm btn-primary" onClick={() => setGemini(true)}><SparkleIcon size={16} /> Research with Gemini</button>
          <button className="btn btn-sm btn-soft" onClick={() => void copy()}><CopyIcon size={16} /> Copy research brief</button>
          <button className="btn btn-sm btn-soft" onClick={() => setAdding(true)}><PlusIcon size={16} /> Add the research</button>
          <button className="btn btn-sm btn-ghost" onClick={() => void act("snooze")}>Snooze 30 days</button>
          <button className="btn btn-sm btn-ghost" onClick={() => void act("dismiss")}>Not worth it</button>
        </div>
      </section>
      <GeminiRunLine person={person} />
      {gemini && <GeminiDialog people={[person]} onClose={() => setGemini(false)} />}
      {adding && <AddResearchDialog person={person} onClose={() => setAdding(false)} />}
      {shown && <BriefDialog text={shown} onClose={() => setShown(null)} />}
    </>
  );
}
