// Sediment's section on the Settings page: which AI takes readings, and whether it reads meeting transcripts.
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
  const { data: job } = useLive(sedimentApi.ai);
  const { data: providers } = useLive<ProviderInfo[]>(api.providers);
  const options = [
    { value: "auto", label: "Same as the app", hint: "Or the cloud AI, if setup put careful jobs there" },
    ...(providers ?? []).map((p) => ({ value: p.id, label: p.label, hint: p.ready ? "Ready" : p.kind === "local" ? "Not running" : "Needs setup" })),
  ];
  return (
    <Section icon={<LinesIcon size={16} />} title="Sediment" blurb="How people seem to feel, read by AI from what's on file. Keys and models are set up under AI above.">
      <ControlRow
        label="Readings"
        hint={
          <>
            Judges how someone feels about you, your company or your product.{" "}
            {job && <span className={job.ready ? "text-forest-deep" : "text-ink"}>{job.ready ? `${job.label} · ${job.model}` : job.reason}</span>}
          </>
        }
      >
        <Select label="Readings" size="sm" className="w-full sm:w-64" value={(get<string>("sediment.reading_provider") as string) || "auto"} options={options}
          onChange={(v) => void save({ "sediment.reading_provider": v })} />
      </ControlRow>
      <SwitchRow
        label="Read meeting transcripts"
        hint="Off: readings use summaries and notes only, and less is sent to the AI. On: what they said in meetings is read too, which tells the most."
        checked={!!get<boolean>("sediment.transcripts")}
        onChange={(v) => void save({ "sediment.transcripts": v })}
      />
    </Section>
  );
}
