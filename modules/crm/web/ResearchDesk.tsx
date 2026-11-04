// The Research page: everyone you could research, by how far it has got, and batches of them started in one go: a cheap
// first pass with Gemini, deep research through an AI tool on your own plan (which starts from what the first pass
// found), or both, one after the other.
import { useState } from "react";
import { AlertIcon, CheckIcon, ClockIcon, SearchIcon, SparkleIcon } from "@core/components/icons";
import { PageHeader, Segmented, Select, Skeleton, Spinner, useConfirm } from "@core/components/ui";
import { words } from "@core/api";
import { useLive } from "@core/live";
import { useSettings, useShell } from "@core/shell";
import { crmApi } from "./api";
import type { DeskItem, DeskMark, DeskShow, GeminiOverview, ResearchTool } from "./api";
import { Avatar, roleLine } from "./bits";
import { formatDate } from "./format";
import { money } from "./GeminiResearch";
import { connectionLine } from "./tier";

const SHOWS: { id: DeskShow; label: string; empty: string }[] = [
  { id: "new", label: "No research", empty: "Everyone has been researched, or is under way." },
  { id: "first", label: "First pass only", empty: "No one has only a first pass. People get here when Gemini's first pass is done." },
  { id: "deep", label: "Researched", empty: "No one has been researched deeply yet." },
  { id: "running", label: "Under way", empty: "Nothing is being researched right now." },
  { id: "skipped", label: "Skipped", empty: "No one is snoozed, marked not worth it, or missing a surname." },
];
const PAGE = 50;
const TOOL_NAMES: Record<ResearchTool["id"], string> = { claude: "Claude Code", codex: "Codex", gemini_cli: "Gemini CLI" };
const by = (via: DeskMark["via"]) => (via === "api" ? "Gemini" : via === "you" ? "a report you added" : TOOL_NAMES[via]);

type Pass = "both" | "first" | "deep";

/** How the two passes run: Gemini's level and cost, the AI tool for deep research, and whether reports wait for you. */
function HowItRuns({ data, deep, setDeep }: { data: GeminiOverview; deep: ResearchTool | undefined; setDeep: (id: string) => void }) {
  const { get, save } = useSettings();
  const lv = data.levels.find((l) => l.id === data.level);
  const each = lv ? (data.batch ? lv.estimate_batch : lv.estimate) : 0;
  const free = lv ? (data.batch ? lv.free_estimate_batch : lv.free_estimate) : 0;
  const room = Math.max(0, Math.floor((data.budget - data.spent) / Math.max(each, 0.001)));
  return (
    <section className="panel mb-6 grid animate-enter gap-x-6 gap-y-4 p-4 sm:grid-cols-2 sm:px-5">
      <div className="min-w-0">
        <p className="text-label font-medium">1. First pass, with Gemini</p>
        <p className="mt-0.5 text-hint text-ink-soft">
          {data.ready
            ? <>Gemini {lv?.label ?? data.level} searches Google and writes a short report with your key{data.batch ? ", through Batch" : ""}: about {money(free)} a person while Google&apos;s {data.free_searches.toLocaleString()} free searches a month last (about {Math.floor(data.free_searches / Math.max(lv?.searches_each ?? 1, 1))} people), {money(each)} after. The budget counts every search at full price: {money(data.spent)} of ${data.budget} used this month, room for about {room} more. <a href="#/settings" className="underline">Change</a></>
            : <span className="text-trail-deep">{data.reason}</span>}
        </p>
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-label font-medium">2. Deep research, with</p>
          <Select label="Deep research with" size="sm" className="w-44" value={deep?.id ?? ""}
            options={data.tools.map((t) => ({ value: t.id, label: t.label, hint: t.ready ? `On ${t.plan}` : "Not ready" }))}
            onChange={setDeep} />
        </div>
        <p className="mt-1 text-hint text-ink-soft">
          {deep?.ready
            ? `On ${deep.plan}, nothing charged here. It starts from what the first pass found and goes further, one person at a time, a few minutes each. When the plan's limit is reached it waits and carries on.`
            : <span className="text-trail-deep">{deep?.reason ?? `No AI tool is set up on ${words.here}.`}</span>}
        </p>
      </div>
      <label className="flex items-start gap-2.5 border-t border-line pt-3 text-ui text-ink-soft sm:col-span-2">
        <input type="checkbox" className="mt-1 accent-forest" checked={get<boolean>("crm.research_auto_add") ?? true}
          onChange={(e) => void save({ "crm.research_auto_add": e.target.checked })} />
        <span>
          <span className="font-medium text-ink">Add reports to people by themselves.</span> A report that&apos;s sure it found the right
          person is added without waiting in the Inbox. Doubtful ones still wait for you.
        </span>
      </label>
    </section>
  );
}

function Mark({ label, mark }: { label: string; mark: DeskMark }) {
  const text = `${label} · ${mark.via === "api" || mark.via === "you" ? "" : `${TOOL_NAMES[mark.via]} · `}${formatDate(mark.at, { year: undefined })}`;
  const chip = `chip ${mark.waiting ? "bg-sun-soft text-sun-deep" : "bg-forest-soft text-forest-deep"}`;
  const tip = mark.waiting ? "The report is waiting in the Inbox for your OK" : `By ${by(mark.via)}. Open the report`;
  return mark.inbox_id
    ? <a href={`#/crm/inbox/${mark.inbox_id}`} className={`${chip} hover:underline`} data-tip={tip}>{mark.waiting ? <ClockIcon size={12} /> : <CheckIcon size={12} />} {text}</a>
    : <span className={chip}><CheckIcon size={12} /> {text}</span>;
}

function Row({ item, picked, onPick }: { item: DeskItem; picked: boolean; onPick: (on: boolean) => void }) {
  const { toast } = useShell();
  const { row, run } = item;
  const busy = !!run && ["queued", "running", "waiting"].includes(run.status);
  const act = (fn: () => Promise<unknown>) => void fn().catch((e: Error) => toast(e.message, "error"));
  return (
    <li className="flex flex-wrap items-center gap-x-3.5 gap-y-2 px-4 py-3 sm:px-5">
      <input type="checkbox" className="accent-forest" aria-label={`Choose ${row.person.name}`} checked={picked} disabled={busy}
        onChange={(e) => onPick(e.target.checked)} />
      <Avatar id={row.person.id} name={row.person.name} />
      <a href={`#/crm/e/${row.person.id}`} className="min-w-40 flex-1 basis-48">
        <span className="block truncate text-label font-medium hover:underline">{row.person.name}</span>
        <span className="block truncate text-hint text-ink-soft">{[roleLine(row.title, row.org?.name), connectionLine(row.connection)].filter(Boolean).join(" · ") || " "}</span>
      </a>
      <div className="flex flex-wrap items-center justify-end gap-1.5 text-meta text-ink-soft">
        {item.first && <Mark label="First pass" mark={item.first} />}
        {item.deep && <Mark label="Deep" mark={item.deep} />}
        {busy && run && (
          <>
            <Spinner className="text-ink-faint" />
            <span>
              {run.via === "api" ? "Gemini first pass" : TOOL_NAMES[run.via]}{run.status === "queued" ? ", waiting its turn" : run.status === "waiting" ? ", waiting" : ", searching"}
              {run.then_via && `, then ${TOOL_NAMES[run.then_via]}`}
            </span>
            <button className="btn btn-sm btn-ghost" onClick={() => act(() => crmApi.cancelRun(run.id))}>Cancel</button>
          </>
        )}
        {run?.status === "failed" && (
          <>
            <span className="flex max-w-xs items-center gap-1 truncate text-trail-deep" data-tip={run.error ?? undefined}><AlertIcon size={14} className="shrink-0" /> Didn&apos;t finish: {run.error}</span>
            <button className="btn btn-sm btn-ghost" onClick={() => act(() => crmApi.retryRun(run.id))}>Try again</button>
          </>
        )}
      </div>
    </li>
  );
}

export default function ResearchDesk() {
  const { toast } = useShell();
  const { get, save } = useSettings();
  const [confirm, confirmDialog] = useConfirm();
  const [show, setShow] = useState<DeskShow>("new");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [picked, setPicked] = useState<Map<string, string>>(new Map());
  const [busy, setBusy] = useState(false);
  const { data } = useLive(() => crmApi.researchDesk({ show, q: q.trim() || undefined, limit }), [show, q, limit]);
  const { data: how } = useLive(crmApi.geminiOverview, []);

  const deepId = get<string>("crm.research_deep_via") ?? "claude";
  const deep = how?.tools.find((t) => t.id === deepId) ?? how?.tools.find((t) => t.ready);
  const lv = how?.levels.find((l) => l.id === how.level);
  const each = lv && how ? (how.batch ? lv.estimate_batch : lv.estimate) : 0;
  const pickable = (data?.items ?? []).filter((i) => !(i.run && ["queued", "running", "waiting"].includes(i.run.status)));
  const all = pickable.length > 0 && pickable.every((i) => picked.has(i.row.person.id));

  const choose = (next: DeskShow) => {
    setShow(next);
    setLimit(PAGE);
    setPicked(new Map());
  };
  const pick = (id: string, name: string, on: boolean) => setPicked((m) => {
    const next = new Map(m);
    if (on) next.set(id, name);
    else next.delete(id);
    return next;
  });
  const pickAll = (on: boolean) => setPicked(on ? new Map(pickable.map((i) => [i.row.person.id, i.row.person.name])) : new Map());

  const start = async (pass: Pass) => {
    if (!how || !deep) return;
    const ids = [...picked.keys()];
    const cost = pass === "deep" ? 0 : each * ids.length;
    if (how.warn_over > 0 && cost >= how.warn_over && !(await confirm({
      title: `First pass on ${ids.length} people?`, confirmLabel: "Start",
      body: `Counting every search at full price, Gemini's first pass costs about ${money(each)} a person, so about ${money(cost)} in all. Most of that is Google's fee for each search, and the first ${how.free_searches.toLocaleString()} searches a month are free, so it's often much less. Research stops before it would pass this month's $${how.budget} budget.`,
    }))) return;
    setBusy(true);
    try {
      const r = pass === "deep"
        ? await crmApi.startGemini(ids, how.level, how.batch, deep.id)
        : await crmApi.startGemini(ids, how.level, how.batch, "api", pass === "both" ? deep.id : null);
      const why = r.skipped.length ? ` ${r.skipped.length} skipped: ${r.skipped[0].reason}${r.skipped.length > 1 ? ", …" : ""}.` : "";
      const what = pass === "both" ? `A first pass with Gemini, then deep research with ${deep.label}` : pass === "first" ? "A first pass with Gemini" : `Deep research with ${deep.label}`;
      toast(r.started ? `${what}, on ${r.started === 1 ? "1 person" : `${r.started} people`}.${why}` : `Nothing started.${why}`, r.started ? "success" : "error");
      setPicked(new Map());
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const n = picked.size;
  const firstOk = !!how?.ready;
  const deepOk = !!deep?.ready;
  const counts = data?.counts;
  return (
    <div>
      <PageHeader title="Research" subtitle="Learn who people are and how they connect to you. Run a cheap first pass on everyone, then deep research on the ones who matter, which picks up where the first pass left off." />
      {how && <HowItRuns data={how} deep={deep} setDeep={(id) => void save({ "crm.research_deep_via": id })} />}

      <div className="mb-3 space-y-3">
        <div className="-mx-1 overflow-x-auto px-1 pb-1">
          <Segmented kind="tab" label="Research" value={show} onChange={choose}
            options={SHOWS.map((s) => ({ id: s.id, label: <>{s.label} {counts && <span className="tabular-nums text-ink-soft">{counts[s.id]}</span>}</> }))} />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-ui text-ink-soft">
            <input type="checkbox" className="accent-forest" checked={all} disabled={!pickable.length} onChange={(e) => pickAll(e.target.checked)} />
            {n ? `${n} chosen` : `Choose all ${pickable.length} shown`}
          </label>
          <div className="relative ml-auto min-w-48 max-w-xs flex-1">
            <SearchIcon size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
            <input className="field h-10 w-full pl-9" placeholder="Search names and organizations" aria-label="Search people" value={q}
              onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} />
          </div>
        </div>
      </div>

      {!data ? <Skeleton className="h-64 w-full rounded-xl" /> : data.items.length === 0 ? (
        <p className="inset-surface px-5 py-4 text-ui text-ink-soft">{q.trim() ? "No one here matches that." : SHOWS.find((s) => s.id === show)?.empty}</p>
      ) : (
        <>
          <ul className="panel divide-y divide-line overflow-hidden">
            {data.items.map((i) => (
              <Row key={i.row.person.id} item={i} picked={picked.has(i.row.person.id)} onPick={(on) => pick(i.row.person.id, i.row.person.name, on)} />
            ))}
          </ul>
          {data.total > data.items.length && (
            <div className="mt-3 flex justify-center">
              <button className="btn btn-sm btn-ghost" onClick={() => setLimit((l) => l + PAGE)}>Show {Math.min(PAGE, data.total - data.items.length)} more of {data.total - data.items.length}</button>
            </div>
          )}
        </>
      )}

      {n > 0 && (
        <div className="sticky bottom-4 z-10 mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-surface px-4 py-3 shadow-lg">
          <span className="mr-auto text-label font-medium">{n === 1 ? [...picked.values()][0] : `${n} people`}</span>
          {show !== "first" && show !== "deep" && (
            <button className="btn btn-sm btn-primary" disabled={busy || !firstOk || !deepOk} onClick={() => void start("both")}
              data-tip={firstOk && deepOk ? `Gemini's first pass, then deep research with ${deep?.label} on ${deep?.plan}, starting from what it found` : undefined}>
              {busy ? <Spinner /> : <SparkleIcon size={16} />} First pass, then deep
            </button>
          )}
          {show !== "first" && (
            <button className="btn btn-sm btn-soft" disabled={busy || !firstOk} onClick={() => void start("first")}>First pass only</button>
          )}
          <button className={`btn btn-sm ${show === "first" || show === "deep" ? "btn-primary" : "btn-soft"}`} disabled={busy || !deepOk} onClick={() => void start("deep")}>
            {show === "first" && <SparkleIcon size={16} />} {show === "deep" ? "Research deeply again" : "Deep research"}{deep ? ` with ${deep.label}` : ""}
          </button>
          <button className="btn btn-sm btn-ghost" onClick={() => setPicked(new Map())}>Clear</button>
        </div>
      )}
      {confirmDialog}
    </div>
  );
}
