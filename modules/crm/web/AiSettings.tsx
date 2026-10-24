// The People module's section on the Settings page: which AI does each of its jobs.
import { useState } from "react";
import { api } from "@core/api";
import type { ProviderInfo } from "@core/api";
import { Section } from "@core/components/blocks";
import { AlertIcon, CheckIcon, SparkleIcon } from "@core/components/icons";
import { ControlRow, Select, Spinner, SwitchRow } from "@core/components/ui";
import { useLive } from "@core/live";
import { useSettings, useShell } from "@core/shell";
import { crmApi } from "./api";
import CaptureSettings from "./Capture";
import { GeminiSettings } from "./GeminiResearch";
import PictureSettings from "./PictureSettings";
import SheetSettings from "./SheetSettings";
import type { AiRole } from "./api";

function Job({ job, providers }: { job: AiRole; providers: ProviderInfo[] }) {
  const { save } = useSettings();
  const { toast } = useShell();
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const options = [
    { value: "auto", label: "Same as the app", hint: "The provider and fallback chosen above" },
    ...(job.rules ? [{ value: "rules", label: "Rules only (no AI)", hint: "A plain reading that you always review" }] : []),
    ...providers.map((p) => ({ value: p.id, label: p.label, hint: p.ready ? "Ready" : p.kind === "local" ? "Not running" : "Needs setup" })),
  ];
  const test = async () => {
    setTesting(true);
    setResult(null);
    try {
      setResult({ ok: true, text: (await api.providerTest(job.provider as ProviderInfo["id"])).message });
    } catch (e) {
      setResult({ ok: false, text: (e as Error).message });
    } finally {
      setTesting(false);
    }
  };
  return (
    <div className="py-3.5">
      <ControlRow
        label={job.label}
        hint={
          <>
            {job.hint}{" "}
            <span className={job.ready ? "text-forest-deep" : "text-ink"}>
              {job.ready ? `${job.providerLabel} · ${job.model}` : job.reason}
            </span>
          </>
        }
        className="!py-0"
      >
        <Select label={job.label} size="sm" className="w-full sm:w-64" value={job.choice} options={options} onChange={(v) => void save({ [job.setting]: v })} />
      </ControlRow>
      <div className="mt-2.5">
        <button className="btn btn-sm btn-soft" disabled={testing || !job.ready || job.provider === "rules"} onClick={() => void test().catch((e) => toast(e.message, "error"))}>
          {testing ? <Spinner /> : <SparkleIcon size={16} />}
          Test this job
        </button>
        {result && (
          <p className={`mt-2.5 flex animate-fade-in items-start gap-1.5 text-hint leading-snug ${result.ok ? "text-forest-deep" : "text-trail-deep"}`}>
            {result.ok ? <CheckIcon size={16} className="shrink-0" /> : <AlertIcon size={16} className="shrink-0" />}
            <span className="break-words">{result.text}</span>
          </p>
        )}
      </div>
    </div>
  );
}

/** What works on this Mac with no keys, what needs an AI key, and what needs another service (and so Lockdown off). */
function WhatNeedsTheCloud() {
  const rows: { title: string; body: string }[] = [
    { title: "Works on this Mac, with nothing set up", body: "Your people, organizations, network and groups. Importing a spreadsheet or LinkedIn export. Adding notes and documents (a small model writes the summary and action items; rules find the people; you look each one over first). Overviews and questions about a person. Backups, exports and pictures you add yourself." },
    { title: "Needs an AI key for the best results", body: "Reading notes and documents carefully, so relationships and facts are found too (Claude, Gemini or OpenAI), and Research by Gemini." },
    { title: "Needs another service, so it's off under Lockdown", body: "Research by Gemini, Granola, calendars, the shared Google Sheet, and Gravatar pictures. “Copy research brief” still works: you take it to another tool yourself." },
  ];
  return (
    <Section icon={<SparkleIcon size={16} />} title="People: what works where" blurb="So you know what to expect from each way of running AI.">
      <div className="divide-y divide-line">
        {rows.map((r) => (
          <div key={r.title} className="py-3.5">
            <div className="text-label font-medium">{r.title}</div>
            <p className="mt-1 text-hint leading-snug text-ink-soft">{r.body}</p>
          </div>
        ))}
      </div>
    </Section>
  );
}

export default function AiSettings() {
  const { data: roles } = useLive<AiRole[]>(crmApi.aiRoles);
  const { data: providers } = useLive<ProviderInfo[]>(api.providers);
  const { data: coverage } = useLive(crmApi.overviewCoverage);
  const { get, save } = useSettings();
  return (
    <>
    <Section icon={<SparkleIcon size={16} />} title="People: AI jobs" blurb="Reading what you add is the careful job, sorting is the quick one, and overviews and questions are about one person at a time, so each can use a different provider. Keys and models are set up under AI above.">
      {roles && providers ? roles.map((job) => <Job key={job.role} job={job} providers={providers} />) : <div className="py-6"><Spinner className="text-ink-faint" /></div>}
      <SwitchRow
        label="Write overviews ahead of time"
        hint={
          <>
            Off: an overview is written when you open someone's profile. On: they're written in the background, the people closest to you first, a few every ten minutes.
            {coverage && coverage.people > 0 && <> So far {coverage.written} of {coverage.people} people have one.</>}
          </>
        }
        checked={!!get<boolean>("crm.overviews_ahead")}
        onChange={(v) => void save({ "crm.overviews_ahead": v })}
      />
    </Section>
    <Section icon={<SparkleIcon size={16} />} title="People: notes sent in" blurb="Meetings and notes that arrive from a note-taking app or a webhook.">
      <SwitchRow
        label="Add them to your people automatically"
        hint="Off: each one waits in the Inbox for you to look over. On: it's added unless a name is unclear."
        checked={!!get<boolean>("crm.webhook_auto_apply")}
        onChange={(v) => void save({ "crm.webhook_auto_apply": v })}
      />
    </Section>
    <WhatNeedsTheCloud />
    <GeminiSettings />
    <CaptureSettings />
    <SheetSettings />
    <PictureSettings />
    </>
  );
}
