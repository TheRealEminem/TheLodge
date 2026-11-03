// Picks one of a provider's models from the list the provider itself gives, or a typed id. Used by Settings → AI for each
// provider's own model, and by modules for a job that uses a model of its own.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { ProviderId } from "../api";
import { useSettings } from "../shell";
import { TextSetting } from "./blocks";
import { AlertIcon, RefreshIcon } from "./icons";
import { Select, Spinner } from "./ui";

const OTHER = "\u0000other";

export function ModelPicker({
  provider,
  value,
  onSave,
  blank,
  label = "Model",
}: {
  provider: ProviderId;
  value: string;
  onSave: (v: string) => void;
  /** What an empty value means, offered as the first choice (e.g. "Automatic"). Without it, empty isn't offered. */
  blank?: { label: string; hint?: string };
  label?: string;
}) {
  const { values, hints } = useSettings();
  const [models, setModels] = useState<string[] | null>(null);
  const [error, setError] = useState("");
  const [typing, setTyping] = useState(false);
  const [tries, setTries] = useState(0);
  // What decides whether the provider can answer: a new key, address or Lockdown means asking again.
  const reach = [hints[`ai.${provider}_api_key`], values?.["ai.custom_base_url"], values?.["ai.ollama_url"], values?.["core.lockdown"]].map(String).join("|");
  useEffect(() => {
    let live = true;
    setModels(null);
    setError("");
    api.providerModels(provider).then(
      (r) => live && setModels(r.models),
      (e: Error) => {
        if (!live) return;
        setModels([]);
        setError(e.message);
      },
    );
    return () => {
      live = false;
    };
  }, [provider, reach, tries]);

  const again = (
    <button className="btn btn-sm btn-ghost shrink-0 !px-2" aria-label="Load the model list again" title="Load the model list again" onClick={() => setTries((n) => n + 1)}>
      <RefreshIcon size={16} />
    </button>
  );
  if (models === null) return <Spinner className="text-ink-faint" />;
  if (typing || models.length === 0) {
    return (
      <div className="w-full sm:w-64 sm:shrink-0">
        <div className="flex items-center gap-1">
          <TextSetting label={label} value={value} onSave={onSave} mono className="w-full" placeholder={blank ? blank.label.toLowerCase() : "model id"} />
          {again}
        </div>
        {!typing && (
          <p className="mt-1.5 flex items-start gap-1.5 text-hint leading-snug text-trail-deep">
            <AlertIcon size={14} className="mt-0.5 shrink-0" />
            <span className="break-words">{error ? `Couldn't list the models: ${error.replace(/\.$/, "")}.` : "The provider listed no models."} Type a model id instead.</span>
          </p>
        )}
      </div>
    );
  }
  const options = [
    ...(blank ? [{ value: "", ...blank }] : []),
    ...models.map((m) => ({ value: m, label: m })),
    ...(value && !models.includes(value) ? [{ value, label: value, hint: "Not in the provider's list" }] : []),
    { value: OTHER, label: "Other…", hint: "Type a model id" },
  ];
  return (
    <div className="flex w-full items-center gap-1 sm:w-64 sm:shrink-0">
      <Select label={label} size="sm" className="min-w-0 flex-1" value={value} options={options} onChange={(v) => (v === OTHER ? setTyping(true) : onSave(v))} />
      {again}
    </div>
  );
}
