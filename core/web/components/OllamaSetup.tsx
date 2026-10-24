// Getting a model that runs on this Mac: install Ollama, download the model that suits this Mac, then Ready.
// Shared by the first-run setup and Settings → AI. Each step is a button; the work shows its progress.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { OllamaStatus } from "../api";
import { AlertIcon, CheckIcon, DownloadIcon, LockIcon } from "./icons";
import { Spinner } from "./ui";
import { useLive } from "../live";
import { useShell } from "../shell";

function Progress({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="mt-2.5" role="status">
      <div className="flex items-center gap-2 text-hint text-ink-soft">
        <Spinner /> {label}
        {value != null && ` ${Math.round(value * 100)}%`}
      </div>
      {value != null && (
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-subtle">
          <div className="h-full rounded-full bg-forest transition-[width] duration-300" style={{ width: `${Math.round(value * 100)}%` }} />
        </div>
      )}
    </div>
  );
}

/** Ollama's setup in one card's worth of rows. `onReady` fires once a model is there to use. */
export function OllamaSetup({ onReady }: { onReady?: () => void }) {
  const { toast } = useShell();
  const { data: s, reload } = useLive<OllamaStatus>(api.ollama);
  const [starting, setStarting] = useState(false);
  const working = !!(s?.install?.active || s?.pull?.active || starting);

  useEffect(() => {                                           // progress isn't an event: look again while work runs
    if (!working) return;
    const t = setInterval(() => void reload(), 1500);
    return () => clearInterval(t);
  }, [working, reload]);

  const ready = !!s && s.reachable && s.models.length > 0;
  useEffect(() => {
    if (ready) onReady?.();
  }, [ready, onReady]);

  if (!s) return <div className="py-3.5"><Spinner className="text-ink-faint" /></div>;

  const act = async (start: () => Promise<{ started: boolean }>) => {
    setStarting(true);
    try {
      await start();
      await reload();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setStarting(false);
    }
  };

  const failure = s.install?.error || s.pull?.error;
  let body;
  if (!s.can_install && !s.reachable) {
    body = <p className="text-hint text-ink-soft">Ollama isn't running. Install it from ollama.com and open it, and it shows up here.</p>;
  } else if (!s.installed && !s.reachable) {
    body = (
      <>
        <p className="text-hint text-ink-soft">Ollama is the free app that runs AI models on this Mac. It's a download of about 1 GB, checked against Ollama's own signature before it's installed.</p>
        <button className="btn btn-sm btn-soft mt-3" disabled={working || s.locked} onClick={() => void act(api.ollamaInstall)}>
          <DownloadIcon size={16} /> Install Ollama
        </button>
      </>
    );
  } else if (!s.reachable) {
    body = (
      <>
        <p className="text-hint text-ink-soft">Ollama is installed but not open.</p>
        <button className="btn btn-sm btn-soft mt-3" disabled={working} onClick={() => void act(api.ollamaInstall)}>Open Ollama</button>
      </>
    );
  } else if (!ready) {
    body = (
      <>
        <p className="text-hint text-ink-soft">Ollama is running but has no model yet. {s.recommended} suits this Mac.</p>
        <button className="btn btn-sm btn-soft mt-3" disabled={working || s.locked} onClick={() => void act(() => api.ollamaPull(s.recommended))}>
          <DownloadIcon size={16} /> Download {s.recommended}
        </button>
      </>
    );
  } else {
    body = (
      <p className="flex items-center gap-1.5 text-label text-forest-deep">
        <CheckIcon size={16} /> Ready: {s.using || s.models[0]} runs on this Mac.
      </p>
    );
  }

  return (
    <div className="py-3.5">
      {body}
      {s.install?.active && <Progress label={s.install.status} value={s.install.progress} />}
      {s.pull?.active && <Progress label={`Downloading ${s.pull.model}`} value={s.pull.progress} />}
      {failure && (
        <p className="mt-2.5 flex items-start gap-1.5 text-hint leading-snug text-trail-deep">
          <AlertIcon size={16} className="shrink-0" /> <span className="break-words">{failure}</span>
        </p>
      )}
      {s.locked && !ready && (
        <p className="mt-2.5 flex items-start gap-1.5 text-hint text-ink-soft">
          <LockIcon size={16} className="shrink-0" /> Turn off Lockdown to download it.
        </p>
      )}
    </div>
  );
}
