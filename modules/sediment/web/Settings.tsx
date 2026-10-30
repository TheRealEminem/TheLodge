// Sediment's section on the Settings page: which AI takes readings and plays people, and whether transcripts are read.
import { api } from "@core/api";
import type { ProviderInfo } from "@core/api";
import { Section } from "@core/components/blocks";
import { LinesIcon } from "@core/components/icons";
import { ControlRow, Select, SwitchRow } from "@core/components/ui";
import { useLive } from "@core/live";
import { useSettings } from "@core/shell";
import { sedimentApi } from "./api";

export default function SedimentSettings() {
  const { get, save } = useSettings();
  const { data: jobs } = useLive(sedimentApi.ai);
  const { data: providers } = useLive<ProviderInfo[]>(api.providers);
  const options = [
    { value: "auto", label: "Same as the app", hint: "Readings use the cloud AI if setup put careful jobs there" },
    ...(providers ?? []).map((p) => ({ value: p.id, label: p.label, hint: p.ready ? "Ready" : p.kind === "local" ? "Not running" : "Needs setup" })),
  ];
  return (
    <Section icon={<LinesIcon size={16} />} title="Sediment" blurb="How people seem to feel, read by AI from what's on file. Keys and models are set up under AI above.">
      {[
        { key: "readings" as const, setting: "sediment.reading_provider", label: "Readings", hint: "Judges how someone feels about you, your company or your product." },
        { key: "talk" as const, setting: "sediment.talk_provider", label: "Portraits and rehearsals", hint: "Writes each person's portrait and plays them when you rehearse." },
      ].map((row) => {
        const job = jobs?.[row.key];
        return (
          <ControlRow
            key={row.key}
            label={row.label}
            hint={
              <>
                {row.hint}{" "}
                {job && <span className={job.ready ? "text-forest-deep" : "text-ink"}>{job.ready ? `${job.label} · ${job.model}` : job.reason}</span>}
              </>
            }
          >
            <Select label={row.label} size="sm" className="w-full sm:w-64" value={get<string>(row.setting) || "auto"} options={options}
              onChange={(v) => void save({ [row.setting]: v })} />
          </ControlRow>
        );
      })}
      <SwitchRow
        label="Read meeting transcripts"
        hint="Off: readings use summaries and notes only, and less is sent to the AI. On: what they said in meetings is read too, which tells the most."
        checked={!!get<boolean>("sediment.transcripts")}
        onChange={(v) => void save({ "sediment.transcripts": v })}
      />
    </Section>
  );
}
