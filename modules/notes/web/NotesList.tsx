import { JobChip } from "@core/components/blocks";
import { NoteIcon, PlusIcon } from "@core/components/icons";
import { ContourBadge } from "@core/components/illustrations";
import { PageHeader, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { navigate } from "@core/router";
import { notesApi } from "./api";
import { when } from "./format";

export default function NotesList() {
  const { data: notes } = useLive(notesApi.list);
  const create = async () => navigate(`notes/${(await notesApi.create()).id}`);
  return (
    <>
      <PageHeader
        title="Notes"
        subtitle={notes ? `${notes.length} ${notes.length === 1 ? "note" : "notes"}` : undefined}
        actions={
          <button className="btn btn-md btn-primary" onClick={() => void create()}>
            <PlusIcon size={18} />
            New note
          </button>
        }
      />
      {!notes && (
        <div className="space-y-3">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      )}
      {notes?.length === 0 && (
        <div className="inset-surface animate-enter px-4 py-12 text-center">
          <ContourBadge>
            <NoteIcon size={20} />
          </ContourBadge>
          <p className="mt-3 font-medium">No notes yet</p>
          <p className="mx-auto mt-1 max-w-sm text-label leading-relaxed text-ink-soft">Write one, and its summary and action items will follow.</p>
        </div>
      )}
      {!!notes?.length && (
        <div className="panel animate-enter divide-y divide-line px-2">
          {notes.map((n) => (
            <a key={n.id} href={`#/notes/${n.id}`} className="flex items-center gap-3 rounded-md px-3 py-3.5 transition-colors hover:bg-forest/[.04]">
              <div className="min-w-0 flex-1">
                <div className="truncate text-label font-medium">{n.title}</div>
                <div className="mt-0.5 text-meta tabular-nums text-ink-soft">{when(n.updated_at)}</div>
              </div>
              <JobChip job={n.job} />
            </a>
          ))}
        </div>
      )}
    </>
  );
}
