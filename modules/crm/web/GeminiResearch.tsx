// The Lodge researching people itself with Gemini: the dialog that starts it (with what it will cost), where a run
// is up to on a profile, and its Settings section.
import { useState } from "react";
import { Section } from "@core/components/blocks";
import { AlertIcon, ClockIcon, SearchIcon, SparkleIcon } from "@core/components/icons";
import { ControlRow, Select, Spinner, SwitchRow } from "@core/components/ui";
import { useLive } from "@core/live";
import { navigate } from "@core/router";
import { useSettings, useShell } from "@core/shell";
import { crmApi } from "./api";
import type { Entity, ResearchLevel, ResearchRun } from "./api";
import { Dialog } from "./forms";
import { formatDate } from "./format";

export const money = (n: number) => (n === 0 ? "$0" : n < 0.01 ? "under 1¢" : n < 1 ? `${Math.round(n * 100)}¢` : `$${n.toFixed(2)}`);

const STAGE: Record<ResearchRun["stage"], string> = {
  ask: "searching", check: "checking what's missing", more: "looking up what was missing", write: "writing the report", done: "done",
};

/** Start Gemini research on one person or several. Shows each level's typical cost and what's left of the budget. */
export function GeminiDialog({ people, onClose }: { people: { id: string; name: string }[]; onClose: () => void }) {
  const { toast } = useShell();
  const { data } = useLive(crmApi.geminiOverview, []);
  const [level, setLevel] = useState<ResearchLevel | null>(null);
  const [batch, setBatch] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  if (!data) return null;
  const lv = level ?? data.level;
  const b = batch ?? data.batch;
  const each = data.levels.find((l) => l.id === lv)?.[b ? "estimate_batch" : "estimate"] ?? 0;
  const left = Math.max(0, data.budget - data.spent);
  const who = people.length === 1 ? people[0].name : `${people.length} people`;
  const go = async () => {
    setBusy(true);
    try {
      const r = await crmApi.startGemini(people.map((p) => p.id), lv, b);
      const why = r.skipped.length ? ` ${r.skipped.length} skipped: ${r.skipped[0].reason}${r.skipped.length > 1 ? ", …" : ""}.` : "";
      toast(r.started ? `Researching ${r.started === 1 ? people.find((p) => !r.skipped.some((s) => s.id === p.id))?.name ?? "1 person" : `${r.started} people`}. Reports wait in the Inbox for your OK.${why}` : `Nothing started.${why}`, r.started ? "success" : "error");
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(false);
    }
  };
  return (
    <Dialog title={`Research ${who} with Gemini`} onClose={onClose} width={600}>
      <p className="text-ui text-ink-soft">
        The Lodge asks Gemini six questions about {people.length === 1 ? "them" : "each person"} with Google Search, then has it write the
        report your research brief describes. The report waits in the Inbox for your OK.
      </p>
      {!data.ready && <p className="mt-3 flex items-start gap-1.5 text-ui text-trail-deep"><AlertIcon size={16} className="mt-0.5 shrink-0" />{data.reason}</p>}
      <div className="mt-4 space-y-2" role="radiogroup" aria-label="How thorough">
        {data.levels.map((l) => (
          <label key={l.id} className={`flex cursor-pointer items-start gap-3 rounded-lg border px-4 py-3 ${lv === l.id ? "border-forest bg-forest-soft/40" : "border-line"}`}>
            <input type="radio" name="level" className="mt-1 accent-forest" checked={lv === l.id} onChange={() => setLevel(l.id)} />
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="text-label font-medium">{l.label}</span>
                <span className="text-hint tabular-nums text-ink-soft">about {money(b ? l.estimate_batch : l.estimate)} a person</span>
              </span>
              <span className="mt-0.5 block text-hint text-ink-soft">{l.hint}</span>
            </span>
          </label>
        ))}
      </div>
      <label className="mt-3 flex items-start gap-2.5 text-ui text-ink-soft">
        <input type="checkbox" className="mt-1 accent-forest" checked={b} onChange={(e) => setBatch(e.target.checked)} />
        <span><span className="font-medium text-ink">Use Google Batch.</span> Half the price for Gemini's reading and writing; reports come back within a day, usually in minutes.</span>
      </label>
      <p className="mt-3 text-hint text-ink-soft">
        {people.length > 1 && <>About {money(each * people.length)} for all {people.length}. </>}
        Most of the cost is Google&apos;s fee for each search ($14 per 1,000), and Google gives 5,000 free searches a month, so it&apos;s often less.
        This month: {money(data.spent)} spent of your ${data.budget} budget{left < each * people.length ? `; there's room for about ${Math.floor(left / Math.max(each, 0.001))}` : ""}.
      </p>
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn btn-md btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-md btn-primary" disabled={busy || !data.ready || left < each} onClick={() => void go()}>
          {busy ? <Spinner /> : <SparkleIcon size={18} />} Start research
        </button>
      </div>
    </Dialog>
  );
}

/** On a profile: a Gemini run under way, failed, or done. `offerMore` adds "research again" after a finished one. */
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
  const label = run.level[0].toUpperCase() + run.level.slice(1);
  let body;
  if (["queued", "running", "waiting"].includes(run.status)) {
    body = (
      <>
        <Spinner className="shrink-0 text-ink-faint" />
        <p className="min-w-0 flex-1 text-ui text-ink-soft">
          Gemini is researching {first}: {STAGE[run.stage]}{run.batch ? " (Google Batch, usually minutes)" : ""}.
          {run.status === "waiting" && run.error && <> {run.error}</>}
        </p>
        <button className="btn btn-sm btn-ghost" onClick={() => void act(() => crmApi.cancelRun(run.id))}>Cancel</button>
      </>
    );
  } else if (run.status === "failed") {
    body = (
      <>
        <AlertIcon size={16} className="shrink-0 text-trail-deep" />
        <p className="min-w-0 flex-1 text-ui text-ink-soft">Gemini couldn&apos;t finish researching {first}: {run.error}</p>
        <button className="btn btn-sm btn-ghost" onClick={() => void act(() => crmApi.retryRun(run.id))}>Try again</button>
      </>
    );
  } else {
    if (!offerMore && !run.inbox_id) return null;
    body = (
      <>
        <SearchIcon size={16} className="shrink-0 text-ink-faint" />
        <p className="min-w-0 flex-1 text-ui text-ink-soft">
          Gemini researched {first} on {formatDate(run.finished_at ?? run.created_at)} ({label}, {run.searches} searches, {money(run.cost)}).
        </p>
        {run.inbox_id && <button className="btn btn-sm btn-ghost" onClick={() => navigate(`crm/inbox/${run.inbox_id}`)}>Open the report</button>}
        {offerMore && run.level !== "best" && <button className="btn btn-sm btn-ghost" onClick={() => setAgain(true)}>Research more deeply</button>}
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

/** Settings → People: research with Gemini. */
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
    <Section icon={<SearchIcon size={16} />} title="People: research with Gemini"
      blurb="The Lodge can research people itself with Gemini and Google Search, using your Gemini key from AI above. It only runs when you start it, from a profile or the Needs research list, and each report waits in the Inbox for your OK.">
      {data && !data.ready && <p className="flex items-start gap-1.5 py-3 text-ui text-trail-deep"><AlertIcon size={16} className="mt-0.5 shrink-0" />{data.reason}</p>}
      <ControlRow label="Usual level" hint={data ? data.levels.map((l) => `${l.label}: about ${money(data.batch ? l.estimate_batch : l.estimate)} a person`).join(" · ") : undefined}>
        <Select label="Usual level" size="sm" className="w-full sm:w-48" value={get<string>("crm.research_level") ?? "quick"}
          options={(data?.levels ?? []).map((l) => ({ value: l.id, label: l.label, hint: l.models.join(", ") }))}
          onChange={(v) => void save({ "crm.research_level": v })} />
      </ControlRow>
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
                  {r.level}{r.batch ? ", batch" : ""} · {r.status === "done" ? `${r.searches} searches, ${money(r.cost)}` : r.status === "failed" ? `failed: ${r.error}` : STAGE[r.stage]} · {formatDate(r.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Section>
  );
}
