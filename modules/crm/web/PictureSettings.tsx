// Settings for pictures: pictures are added by hand on a profile; this is the optional Gravatar look-up.
import { useState } from "react";
import { JobStatus, Section } from "@core/components/blocks";
import { SearchIcon } from "@core/components/icons";
import { SwitchRow } from "@core/components/ui";
import { useLive } from "@core/live";
import { useSettings, useShell } from "@core/shell";
import { crmApi } from "./api";

export default function PictureSettings() {
  const { toast } = useShell();
  const { get, save } = useSettings();
  const { data: state } = useLive(crmApi.pictureLookup);
  const [busy, setBusy] = useState(false);
  const on = !!get<boolean>("crm.gravatar");
  const ask = async () => {
    setBusy(true);
    try {
      await crmApi.lookUpPictures();
      toast("Looking for pictures in the background.");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Section icon={<SearchIcon size={16} />} title="People: pictures" blurb="Add a picture on someone's profile by choosing a file, dropping one, or pasting one. Nothing is looked up unless you turn this on.">
      <SwitchRow
        label="Look up pictures on Gravatar"
        hint="For people with an email address. Gravatar is told a scrambled form of the address, never the address or the name, and has pictures only for people who made one there."
        checked={on}
        onChange={(v) => void save({ "crm.gravatar": v })}
      />
      {on && (
        <div className="flex flex-wrap items-center gap-3 py-3.5">
          <button className="btn btn-sm btn-soft" disabled={busy || state?.job?.status === "running"} onClick={() => void ask()}>
            <SearchIcon size={16} /> Look up everyone now
          </button>
          <JobStatus job={state?.job} startLabel="Look up" />
        </div>
      )}
    </Section>
  );
}
