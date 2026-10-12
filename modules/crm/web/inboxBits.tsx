// Words and chips for the inbox, shared by the queue and the review page.
import { StatusChip } from "@core/components/ui";
import type { Tone } from "@core/components/ui";
import type { InboxRow, InboxSource, InboxStatus } from "./api";

export const STATUS: Record<InboxStatus, { label: string; tone: Tone; live?: boolean }> = {
  pending: { label: "Queued", tone: "neutral" },
  processing: { label: "Reading", tone: "sky", live: true },
  review: { label: "Needs review", tone: "sun" },
  applied: { label: "Added", tone: "forest" },
  failed: { label: "Failed", tone: "trail" },
  discarded: { label: "Discarded", tone: "neutral" },
  skipped: { label: "Skipped", tone: "neutral" },
};

export const SOURCE_LABEL: Record<InboxSource, string> = {
  manual_note: "Pasted notes",
  webhook: "Webhook",
  meeting: "Recorded meeting",
  linkedin_csv: "LinkedIn",
  document: "Document",
  spreadsheet: "Spreadsheet",
};

export const CATEGORY_LABEL: Record<string, string> = {
  meeting_notes: "meeting",
  person_profile: "person profile",
  organization_profile: "organization profile",
  internal_document: "internal document",
  reference_material: "reference",
  junk: "junk",
};

export const DOC_TYPE_LABEL: Record<string, string> = {
  meeting_notes: "Meeting notes",
  person_profile: "Person profile",
  organization_profile: "Organization profile",
  document: "Document",
};

const PROVIDER: Record<string, string> = { anthropic: "Claude", openai: "OpenAI", gemini: "Gemini", deepseek: "DeepSeek", ollama: "Ollama", custom: "Other model" };

/** "anthropic:claude-opus-5-5" -> "Claude · claude-opus-5-5"; rules -> "Rules". */
export function extractorLabel(extractor: string | null | undefined): string {
  if (!extractor) return "";
  if (extractor === "rules" || extractor === "heuristic") return "Rules (no AI)";
  const [provider, ...model] = extractor.split(":");
  const name = PROVIDER[provider] ?? provider;
  return model.join(":") ? `${name} · ${model.join(":")}` : name;
}

/** Where an item is: its own state, unless the job reading it is parked or running, which says more. */
export function StatusPill({ row }: { row: Pick<InboxRow, "status" | "work"> }) {
  if (row.status === "pending" || row.status === "processing") {
    if (row.work?.status === "waiting") return <StatusChip tone="sun" label="Paused" />;
    if (row.work?.status === "running") return <StatusChip tone="sky" label={row.work.stage || "Reading"} live />;
  }
  const s = STATUS[row.status];
  return <StatusChip tone={s.tone} label={s.label} live={s.live} />;
}
