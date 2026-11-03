// The Lodge researching people itself, with Gemini or through an AI tool signed in on this Mac (Claude Code, Codex,
// Gemini CLI, on your own plan): the dialog that starts it (with what it will cost), where a run is up to on a
// profile, and its Settings section.
import { useState } from "react";
import { Section } from "@core/components/blocks";
import { ModelPicker } from "@core/components/ModelPicker";
import { AlertIcon, ClockIcon, SearchIcon, SparkleIcon } from "@core/components/icons";
import { ControlRow, Select, Spinner, SwitchRow } from "@core/components/ui";
import { useLive } from "@core/live";
import { navigate } from "@core/router";
import { useSettings, useShell } from "@core/shell";
import { crmApi } from "./api";
import type { Entity, ResearchLevel, ResearchRun, ResearchTool, ResearchVia } from "./api";
import { Dialog } from "./forms";
import { formatDate } from "./format";

export const money = (n: number) => (n === 0 ? "$0" : n < 0.01 ? "under 1¢" : n < 1 ? `${Math.round(n * 100)}¢` : `$${n.toFixed(2)}`);

const STAGE: Record<ResearchRun["stage"], string> = {
  ask: "searching", check: "checking what's missing", more: "looking up what was missing", write: "writing the report", done: "done",
};
const TOOL_NAMES: Record<ResearchTool["id"], string> = { claude: "Claude Code", codex: "Codex", gemini_cli: "Gemini CLI" };
const PLANS: Record<ResearchTool["id"], string> = { claude: "your Claude plan", codex: "your ChatGPT plan", gemini_cli: "your Google AI plan" };

/** Who did a run: Gemini through your key, or the AI tool. */
const by = (run: ResearchRun) => (run.via === "api" ? "Gemini" : TOOL_NAMES[run.via]);

function Choice({ checked, disabled, onPick, label, hint, reason }: { checked: boolean; disabled?: boolean; onPick: () => void; label: string; hint: string; reason?: string | null }) {
  return (
    <label className={`flex items-start gap-3 rounded-lg border px-4 py-3 ${disabled ? "cursor-default opacity-70" : "cursor-pointer"} ${checked ? "border-forest bg-forest-soft/40" : "border-line"}`}>
      <input type="radio" name="research-way" className="mt-1 accent-forest" checked={checked} disabled={disabled} onChange={onPick} />
      <span className="min-w-0 flex-1">
        <span className="text-label font-medium">{label}</span>
        <span className="mt-0.5 block text-hint text-ink-soft">{hint}</span>
        {reason && <span className="mt-1 flex items-start gap-1.5 text-hint text-trail-deep"><AlertIcon size={14} className="mt-0.5 shrink-0" />{reason}</span>}
      </span>
    </label>
  );
}

/** Start research on one person or several: through an AI tool on your own plan (nothing charged here), or with
 *  Gemini through your key, showing each level's typical cost and what's left of the budget. */
export function GeminiDialog({ people, onClose }: { people: { id: string; name: string }[]; onClose: () => void }) {
  const { toast } = useShell();
  const { save } = useSettings();
  const { data } = useLive(crmApi.geminiOverview, []);
  const [level, setLevel] = useState<ResearchLevel | null>(null);
  const [tool, setTool] = useState<ResearchVia | null>(null);
  const [batch, setBatch] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  if (!data) return null;
  // Start on the usual way if it can run now, else on the first tool that can.
  const usable = (v: ResearchVia) => (v === "api" ? data.ready : !!data.tools.find((t) => t.id === v)?.ready);
  const via = tool ?? (usable(data.via) ? data.via : (data.tools.find((t) => t.ready)?.id ?? data.via));
  const picked = data.tools.find((t) => t.id === via);
  const lv = level ?? data.level;
  const b = batch ?? data.batch;
  const ready = picked ? picked.ready : data.ready;
  const each = data.levels.find((l) => l.id === lv)?.[b ? "estimate_batch" : "estimate"] ?? 0;
  const left = Math.max(0, data.budget - data.spent);
  const total = each * people.length;
  const big = !picked && data.warn_over > 0 && total >= data.warn_over;
  const who = people.length === 1 ? people[0].name : `${people.length} people`;
  const go = async () => {
    setBusy(true);
    try {
      const r = await crmApi.startGemini(people.map((p) => p.id), lv, b, via);
      if (via !== data.via) void save({ "crm.research_via": via });
      const why = r.skipped.length ? ` ${r.skipped.length} skipped: ${r.skipped[0].reason}${r.skipped.length > 1 ? ", …" : ""}.` : "";
      toast(r.started ? `Researching ${r.started === 1 ? people.find((p) => !r.skipped.some((s) => s.id === p.id))?.name ?? "1 person" : `${r.started} people`}. Reports wait in the Inbox for your OK.${why}` : `Nothing started.${why}`, r.started ? "success" : "error");
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(false);
    }
  };
  return (
    <Dialog title={`Research ${who}`} onClose={onClose} width={600}>
      <p className="text-ui text-ink-soft">
        The Lodge gives an AI your research brief on {people.length === 1 ? "them" : "each person"}, it searches the web, and the report it
        writes waits in the Inbox for your OK.
      </p>
      <div className="mt-4" role="radiogroup" aria-label="How to research">
        <p className="mb-2 text-label font-medium">On a plan you already pay for</p>
        <div className="space-y-2">
          {data.tools.map((t) => (
            <Choice key={t.id} checked={via === t.id} disabled={!t.ready} onPick={() => setTool(t.id)} label={t.label} hint={t.hint} reason={t.reason} />
          ))}
        </div>
        <p className="mb-2 mt-4 text-label font-medium">With your Gemini API key</p>
        <div className="space-y-2">
          {data.levels.map((l) => (
            <Choice key={l.id} checked={!picked && lv === l.id} disabled={!data.ready}
              onPick={() => { setTool("api"); setLevel(l.id); }} label={l.label} hint={l.hint} />
          ))}
        </div>
        {!data.ready && <p className="mt-2 flex items-start gap-1.5 text-hint text-trail-deep"><AlertIcon size={14} className="mt-0.5 shrink-0" />{data.reason}</p>}
      </div>
      {picked ? (
        <p className="mt-3 text-hint text-ink-soft">
          Nothing is charged here: it counts toward {picked.plan}&apos;s usage limits. People go one at a time, a few minutes each, and if the
          plan&apos;s limit is reached a run waits and tries again later.
        </p>
      ) : (
        <label className="mt-3 flex items-start gap-2.5 text-ui text-ink-soft">
          <input type="checkbox" className="mt-1 accent-forest" checked={b} onChange={(e) => setBatch(e.target.checked)} />
          <span><span className="font-medium text-ink">Use Google Batch.</span> Half the price for Gemini's reading and writing; reports come back within a day, usually in minutes.</span>
        </label>
      )}
      {big && (
        <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-sun-soft px-3 py-2.5 text-ui text-sun-deep">
          <AlertIcon size={16} className="mt-0.5 shrink-0 text-trail-deep" />
          <span>
            This could cost about {money(total)}{people.length > 1 && <> ({people.length} people at about {money(each)} each)</>}. Most of it is Google&apos;s
            fee for each search ($14 per 1,000, the first 5,000 a month free), so it&apos;s often less. {money(data.spent)} spent on research so far this month.
          </span>
        </p>
      )}
      {!picked && (
        <p className="mt-3 text-hint text-ink-soft">
          {left < total ? `This month's research budget ($${data.budget}) has room for about ${Math.floor(left / Math.max(each, 0.001))} more. ` : ""}
          Counts toward your usage, under Settings, AI, Usage.
        </p>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn btn-md btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-md btn-primary" disabled={busy || !ready || (!picked && left < each)} onClick={() => void go()}>
          {busy ? <Spinner /> : <SparkleIcon size={18} />} {big ? "Start anyway" : "Start research"}
        </button>
      </div>
    </Dialog>
  );
}

/** On a profile: a run under way, failed, or done. `offerMore` adds "research again" after a finished one. */
export function GeminiRunLine({ person, offerMore }: { person: Entity; offerMore?: boolean }) {
  const { toast } = useShell();
  const { data } = useLive(() => crmApi.geminiRun(person.id), [person.id]);
  const [again, setAgain] = useState(false);
  const run = data?.run;
  if (!run || run.status === "cancelled") return null;
  const first = person.name.split(" ")[0];
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const who = by(run);
  const how = run.via === "api" ? `${run.level[0].toUpperCase() + run.level.slice(1)}, ${run.searches} searches, ${money(run.cost)}` : `on ${PLANS[run.via]}`;
  let body;
  if (["queued", "running", "waiting"].includes(run.status)) {
    body = (
      <>
        <Spinner className="shrink-0 text-ink-faint" />
        <p className="min-w-0 flex-1 text-ui text-ink-soft">
          {who} is researching {first}: {run.via === "api" ? STAGE[run.stage] : run.status === "queued" ? "waiting its turn" : "searching the web and writing the report"}{run.batch ? " (Google Batch, usually minutes)" : ""}.
          {run.status === "waiting" && run.error && <> {run.error}</>}
        </p>
        <button className="btn btn-sm btn-ghost" onClick={() => void act(() => crmApi.cancelRun(run.id))}>Cancel</button>
      </>
    );
  } else if (run.status === "failed") {
    body = (
      <>
        <AlertIcon size={16} className="shrink-0 text-trail-deep" />
        <p className="min-w-0 flex-1 text-ui text-ink-soft">{who} couldn&apos;t finish researching {first}: {run.error}</p>
        <button className="btn btn-sm btn-ghost" onClick={() => void act(() => crmApi.retryRun(run.id))}>Try again</button>
      </>
    );
  } else {
    if (!offerMore && !run.inbox_id) return null;
    body = (
      <>
        <SearchIcon size={16} className="shrink-0 text-ink-faint" />
        <p className="min-w-0 flex-1 text-ui text-ink-soft">
          {who} researched {first} on {formatDate(run.finished_at ?? run.created_at)} ({how}).
        </p>
        {run.inbox_id && <button className="btn btn-sm btn-ghost" onClick={() => navigate(`crm/inbox/${run.inbox_id}`)}>Open the report</button>}
        {offerMore && run.level !== "best" && <button className="btn btn-sm btn-ghost" onClick={() => setAgain(true)}>{run.via === "api" ? "Research more deeply" : "Research again"}</button>}
      </>
    );
  }
  return (
    <>
      <div className="inset-surface flex flex-wrap items-center gap-3 px-5 py-3">{body}</div>
      {again && <GeminiDialog people={[person]} onClose={() => setAgain(false)} />}
    </>
  );
}

/** Settings → People: research, the usual way, the AI tools on this Mac, and Gemini's levels, models and budget. */
export function GeminiSettings() {
  const { get, save } = useSettings();
  const { data } = useLive(crmApi.geminiOverview, []);
  const [budget, setBudget] = useState<string | null>(null);
  const saveBudget = () => {
    const n = Math.round(Number(budget));
    if (budget !== null && Number.isFinite(n) && n >= 0) void save({ "crm.research_budget": n });
    setBudget(null);
  };
  return (
    <Section icon={<SearchIcon size={16} />} title="People: research"
      blurb="The Lodge can research people itself: through Claude Code, Codex or Gemini CLI signed in on this Mac, on a plan you already pay for, or with Gemini and Google Search through your Gemini key from AI above. It only runs when you start it, from a profile or the Needs research list, and each report waits in the Inbox for your OK.">
      <ControlRow label="Usual way" hint="What the research dialog starts on. It remembers the last one you used.">
        <Select label="Usual way" size="sm" className="w-full sm:w-56" value={get<string>("crm.research_via") ?? "api"}
          options={[...(data?.tools ?? []).map((t) => ({ value: t.id, label: t.label, hint: t.ready ? `On ${t.plan}` : "Not ready" })),
            { value: "api", label: "Gemini, with your key", hint: "Costs per person" }]}
          onChange={(v) => void save({ "crm.research_via": v })} />
      </ControlRow>
      {data && (
        <div className="py-3.5">
          <p className="mb-2 text-label font-medium">AI tools on this Mac</p>
          <ul className="space-y-1.5 text-ui">
            {data.tools.map((t) => (
              <li key={t.id} className="flex items-start gap-2">
                {t.ready ? <SparkleIcon size={14} className="mt-1 shrink-0 text-forest" /> : <AlertIcon size={14} className="mt-1 shrink-0 text-trail-deep" />}
                <span><span className="font-medium">{t.label}</span> <span className="text-hint text-ink-soft">{t.ready ? `ready, on ${t.plan}` : t.reason}</span></span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {data && !data.ready && <p className="flex items-start gap-1.5 py-3 text-ui text-trail-deep"><AlertIcon size={16} className="mt-0.5 shrink-0" />{data.reason}</p>}
      <ControlRow label="Gemini level" hint={data ? data.levels.map((l) => `${l.label}: about ${money(data.batch ? l.estimate_batch : l.estimate)} a person`).join(" · ") : undefined}>
        <Select label="Gemini level" size="sm" className="w-full sm:w-48" value={get<string>("crm.research_level") ?? "quick"}
          options={(data?.levels ?? []).map((l) => ({ value: l.id, label: l.label, hint: l.models.join(", ") }))}
          onChange={(v) => void save({ "crm.research_level": v })} />
      </ControlRow>
      {data?.ready && (
        <>
          <ControlRow label="Model for searching" hint="Asks the questions with Google Search. Instead of the level's own, at every level.">
            <ModelPicker provider="gemini" label="Model for searching" value={get<string>("crm.research_ask_model") ?? ""}
              blank={{ label: "The level's own", hint: data.level_models.ask }} onSave={(m) => void save({ "crm.research_ask_model": m })} />
          </ControlRow>
          <ControlRow label="Model for writing" hint="Checks what's missing (Best) and writes the report. A model without a listed price is costed at the Pro price.">
            <ModelPicker provider="gemini" label="Model for writing" value={get<string>("crm.research_write_model") ?? ""}
              blank={{ label: "The level's own", hint: data.level_models.write }} onSave={(m) => void save({ "crm.research_write_model": m })} />
          </ControlRow>
        </>
      )}
      <SwitchRow label="Use Google Batch" hint="Half the price for Gemini's reading and writing; reports come back within a day, usually in minutes. Search fees are the same either way."
        checked={!!get<boolean>("crm.research_batch")} onChange={(v) => void save({ "crm.research_batch": v })} />
      <ControlRow label="Monthly budget" hint={data ? `Spent this month: ${money(data.spent)}. Research stops before it would go over. Prices as of ${data.prices_as_of}.` : undefined}>
        <span className="inline-flex items-center gap-1.5 text-ui">
          $<input className="field h-9 w-20 px-2 tabular-nums" inputMode="numeric" aria-label="Monthly budget in dollars"
            value={budget ?? String(get<number>("crm.research_budget") ?? 5)} onChange={(e) => setBudget(e.target.value)}
            onBlur={saveBudget} onKeyDown={(e) => e.key === "Enter" && saveBudget()} />
        </span>
      </ControlRow>
      {data && data.runs.length > 0 && (
        <div className="py-3.5">
          <p className="mb-2 text-label font-medium">Recent research</p>
          <ul className="space-y-1.5 text-ui">
            {data.runs.slice(0, 8).map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
                {["queued", "running", "waiting"].includes(r.status) ? <Spinner className="text-ink-faint" /> : <ClockIcon size={14} className="text-ink-faint" />}
                <a href={`#/crm/e/${r.person_id}`} className="min-w-0 truncate font-medium hover:underline">{r.person ?? "Someone removed"}</a>
                <span className="text-hint text-ink-soft">
                  {r.via === "api" ? `${r.level}${r.batch ? ", batch" : ""}` : by(r)} · {r.status === "done" ? (r.via === "api" ? `${r.searches} searches, ${money(r.cost)}` : `on ${PLANS[r.via]}`) : r.status === "failed" ? `failed: ${r.error}` : r.via === "api" ? STAGE[r.stage] : r.status} · {formatDate(r.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Section>
  );
}
