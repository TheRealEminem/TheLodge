// Quick export: what's on file about one person or organization, as Markdown to copy (into an AI chat, say) or to save
// as a Markdown or PDF file (the server half is quick_export.py).
import { useRef, useState } from "react";
import { inApp, revealInFinder } from "@core/api";
import { CheckIcon, CopyIcon, DocIcon } from "@core/components/icons";
import { Skeleton, Spinner } from "@core/components/ui";
import { useLive } from "@core/live";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { Entity } from "./api";
import { Dialog } from "./forms";

export function QuickExportDialog({ entity, onClose }: { entity: Entity; onClose: () => void }) {
  const { toast } = useShell();
  const { data, error } = useLive(() => crmApi.quickExport(entity.id), [entity.id]);
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState<"md" | "pdf" | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  // The text is already here, so the copy starts inside the click (which WebKit requires). If it's refused anyway,
  // the text is selected so ⌘C finishes the job.
  const copy = () => {
    if (!data) return;
    navigator.clipboard.writeText(data.markdown).then(
      () => { setCopied(true); setTimeout(() => setCopied(false), 1600); },
      () => { box.current?.focus(); box.current?.select(); toast("The clipboard didn't take it, so the text is selected: press ⌘C."); },
    );
  };
  const save = async (format: "md" | "pdf") => {
    setSaving(format);
    try {
      const saved = await crmApi.saveExport(entity.id, format);
      if (inApp) {
        revealInFinder(saved.path);
      } else {
        const a = document.createElement("a");
        a.href = crmApi.exportFileUrl(saved.name);
        a.download = saved.name;
        a.click();
      }
      toast(`Saved ${saved.name}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(null);
    }
  };

  return (
    <Dialog title={`Export ${entity.name}`} onClose={onClose} width={680}>
      <p className="text-ui text-ink-soft">
        What's on file about {entity.name}, as Markdown: copy it into an AI chat, or save it as a file. Email addresses and
        phone numbers are left out, and nothing is sent anywhere from here.
      </p>
      {error ? (
        <p className="mt-3 text-ui text-trail-deep">{error}</p>
      ) : !data ? (
        <Skeleton className="mt-3 h-72 w-full rounded-lg" />
      ) : (
        <>
          <textarea ref={box} className="field mt-3 h-72 w-full resize-none p-3 font-mono text-hint" readOnly aria-label={`${entity.name} as Markdown`}
            value={data.markdown} onFocus={(e) => e.currentTarget.select()} />
          <p className="mt-1.5 text-meta text-ink-soft">{data.characters.toLocaleString()} characters</p>
        </>
      )}
      <div className="mt-4 flex flex-wrap justify-between gap-2">
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-md btn-soft" disabled={!data || !!saving} onClick={() => void save("md")}>
            {saving === "md" ? <Spinner /> : <DocIcon size={18} />} Save as Markdown
          </button>
          <button className="btn btn-md btn-soft" disabled={!data || !!saving} onClick={() => void save("pdf")}>
            {saving === "pdf" ? <Spinner /> : <DocIcon size={18} />} Save as PDF
          </button>
        </div>
        <button className="btn btn-md btn-primary" disabled={!data} onClick={copy}>
          {copied ? <CheckIcon size={18} /> : <CopyIcon size={18} />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {inApp && <p className="mt-3 text-hint text-ink-soft">Saved files go in your data folder, under crm/exports, and open in Finder.</p>}
    </Dialog>
  );
}
