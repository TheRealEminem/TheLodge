import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { JobStatus, LinkedList } from "@core/components/blocks";
import { BackIcon, RefreshIcon, SparkleIcon, TrashIcon } from "@core/components/icons";
import { Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import type { RouteProps } from "@core/registry";
import { navigate } from "@core/router";
import { useShell } from "@core/shell";
import { notesApi } from "./api";
import { when } from "./format";

/** Saves what you type a moment after you stop typing (and when you leave the field). */
function useAutosave(id: string, field: "title" | "body", initial: string | undefined) {
  const [value, setValue] = useState(initial ?? "");
  const [state, setState] = useState<"saved" | "editing" | "saving">("saved");
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const { toast } = useShell();
  useEffect(() => {
    if (initial !== undefined && state === "saved") setValue(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);
  const flush = async (v = value) => {
    clearTimeout(timer.current);
    if (v === initial) return setState("saved");
    setState("saving");
    try {
      await notesApi.patch(id, { [field]: v });
      setState("saved");
    } catch (e) {
      toast((e as Error).message, "error");
      setState("editing");
    }
  };
  const change = (v: string) => {
    setValue(v);
    setState("editing");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => void flush(v), 900);
  };
  return { value, change, flush, state };
}

export default function NoteView({ params }: RouteProps) {
  const { confirm, toast } = useShell();
  const { data: note, error } = useLive(() => notesApi.get(params.id), [params.id]);
  const title = useAutosave(params.id, "title", note?.title);
  const body = useAutosave(params.id, "body", note?.body);

  if (error) {
    return (
      <p className="text-label text-ink-soft">
        {error}. <a className="text-forest underline decoration-forest/30 underline-offset-2" href="#/notes">Back to notes</a>
      </p>
    );
  }
  if (!note) {
    return (
      <div className="space-y-4 pt-2">
        <Skeleton className="h-3.5 w-40" />
        <Skeleton className="h-9 w-2/3" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  const remove = async () => {
    if (!(await confirm({ title: "Delete this note?", body: "Its summary goes with it. Tasks that came from it stay.", confirmLabel: "Delete", tone: "danger" }))) return;
    await notesApi.remove(note.id);
    toast("Note deleted.");
    navigate("notes");
  };
  const saving = title.state !== "saved" || body.state !== "saved";

  return (
    <article className="animate-enter">
      <div className="mb-3 flex items-center justify-between gap-3">
        <a href="#/notes" className="btn btn-sm btn-ghost -ml-3">
          <BackIcon size={16} />
          Notes
        </a>
        <div className="flex items-center gap-1">
          <span className="mr-2 text-meta text-ink-soft" aria-live="polite">
            {saving ? "Saving…" : `Saved ${when(note.updated_at)}`}
          </span>
          <button className="icon-btn hover:!bg-trail-soft hover:!text-trail-deep" aria-label="Delete note" data-tip="Delete" onClick={() => void remove()}>
            <TrashIcon size={18} />
          </button>
        </div>
      </div>

      <input
        aria-label="Title"
        className="page-title w-full bg-transparent outline-none placeholder:text-ink-faint"
        value={title.value}
        placeholder="Untitled note"
        onChange={(e) => title.change(e.target.value)}
        onBlur={() => void title.flush()}
      />
      <textarea
        aria-label="Note"
        className="field mt-5 min-h-[240px] w-full resize-y px-4 py-3 text-body leading-relaxed"
        placeholder="Write anything. Action items in it become tasks once it's summarized."
        value={body.value}
        onChange={(e) => body.change(e.target.value)}
        onBlur={() => void body.flush()}
      />

      <div className="mt-6">
        <JobStatus job={note.job} startLabel="Summarize" />
      </div>

      {note.summary && (
        <section className="panel mt-6 animate-enter p-5 sm:p-7">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2.5 text-heading font-semibold tracking-[-0.01em]">
              <span className="well well-forest h-7 w-7">
                <SparkleIcon size={16} />
              </span>
              Summary
            </h2>
            <button className="btn btn-sm btn-ghost" onClick={() => void notesApi.summarize(note.id)} data-tip={note.summary_by ? `Written by ${note.summary_by}` : undefined}>
              <RefreshIcon size={16} />
              Redo
            </button>
          </div>
          <div className="prose-family">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{note.summary}</ReactMarkdown>
          </div>
        </section>
      )}

      <LinkedList of={`notes:${note.id}`} />
    </article>
  );
}
