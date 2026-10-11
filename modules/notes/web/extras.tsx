// The notes module's Home card and its section on the Settings page.
import { Section } from "@core/components/blocks";
import { NoteIcon, SparkleIcon } from "@core/components/icons";
import { SwitchRow } from "@core/components/ui";
import { useLive } from "@core/live";
import { useSettings } from "@core/shell";
import { notesApi } from "./api";
import { when } from "./format";

export function NotesHome() {
  const { data: notes } = useLive(notesApi.list);
  const waiting = notes?.filter((n) => n.job?.status === "waiting").length ?? 0;
  return (
    <>
      <div className="flex items-center gap-3">
        <span className="well well-forest">
          <NoteIcon size={16} />
        </span>
        <div className="min-w-0">
          <h2 className="text-heading font-semibold tracking-[-0.01em]">Notes</h2>
          <p className="text-hint text-ink-soft">
            {notes ? `${notes.length} ${notes.length === 1 ? "note" : "notes"}${waiting ? ` · ${waiting} waiting for you` : ""}` : "…"}
          </p>
        </div>
      </div>
      <div className="mt-3 space-y-px">
        {notes?.slice(0, 3).map((n) => (
          <a key={n.id} href={`#/notes/${n.id}`} className="-mx-2 flex items-center justify-between gap-3 rounded-md px-2 py-2 text-ui transition-colors hover:bg-forest/[.05]">
            <span className="truncate font-medium">{n.title}</span>
            <span className="shrink-0 text-meta tabular-nums text-ink-soft">{when(n.updated_at)}</span>
          </a>
        ))}
      </div>
      <a href="#/notes" className="btn btn-sm btn-ghost -ml-3 mt-2">
        All notes
      </a>
    </>
  );
}

export function NotesSettings() {
  const { get, save } = useSettings();
  return (
    <Section icon={<NoteIcon size={16} />} title="Notes" blurb="How notes are summarized.">
      <SwitchRow
        icon={<SparkleIcon size={16} />}
        label="Summarize automatically"
        hint="Off: a note waits for you to press “Summarize”."
        checked={!!get<boolean>("notes.auto_summarize")}
        onChange={(v) => void save({ "notes.auto_summarize": v })}
      />
    </Section>
  );
}
