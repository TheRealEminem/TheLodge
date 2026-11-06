// Settings → AI usage: what the app's AI calls cost (core/server/pricing.py). This month's total, the last 30 days by
// provider and by module, and the latest calls. A model with no published price is "unknown", never counted as free.
import { Receipt } from "lucide-react";
import { api } from "../api";
import type { AIUsage as Usage, UsageCall, UsageGroup, UsageTotals } from "../api";
import { Section } from "../components/blocks";
import { icon } from "../components/icons";
import { ControlRow, StatusChip } from "../components/ui";
import { formatDate } from "../format";
import { useLive } from "../live";

const ReceiptIcon = icon(Receipt);

/** "$1.23", or "$0.0042" for a fraction of a cent. */
function money(n: number) {
  if (n > 0 && n < 0.0001) return "< $0.0001";
  const digits = n > 0 && n < 0.01 ? 4 : 2;
  return n.toLocaleString(undefined, { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function tokens(n: number) {
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n);
}

function plural(n: number, one: string, many = `${one}s`) {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

/** "12 calls · 1 failed · 3 stopped by Lockdown · 2 at an unknown price" */
function counts(t: UsageTotals) {
  return [
    plural(t.calls, "call"),
    t.failed ? `${t.failed.toLocaleString()} failed` : "",
    t.stopped ? `${t.stopped.toLocaleString()} stopped by Lockdown` : "",
    t.unknown ? `${t.unknown.toLocaleString()} at an unknown price` : "",
  ].filter(Boolean).join(" · ");
}

function when(iso: string) {
  const d = new Date(iso);
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString() ? time : `${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}, ${time}`;
}

function Breakdown({ title, rows }: { title: string; rows: UsageGroup[] }) {
  return (
    <div className="min-w-0">
      <p className="eyebrow mb-1">{title}</p>
      <ul className="divide-y divide-line">
        {rows.map((r) => (
          <li key={r.id} className="flex items-baseline justify-between gap-3 py-2">
            <span className="min-w-0 truncate text-ui text-ink">{r.label}</span>
            <span className="shrink-0 text-right text-ui tabular-nums text-ink">
              {r.unknown === r.calls ? (
                <span className="text-ink-soft">Unknown</span>
              ) : (
                <>
                  {money(r.cost)}
                  {r.unknown > 0 && <span className="text-ink-soft"> + {r.unknown} unknown</span>}
                </>
              )}
              <span className="ml-1.5 text-meta text-ink-soft">{plural(r.calls, "call")}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Call({ c }: { c: UsageCall }) {
  const who = c.job ? `${c.module_label} · ${c.job}` : c.module_label;
  const used = c.input_tokens !== null && c.output_tokens !== null ? `${tokens(c.input_tokens)} in · ${tokens(c.output_tokens)} out` : "";
  return (
    <li className="flex items-center justify-between gap-x-4 gap-y-1 py-2.5">
      <div className="min-w-0">
        <div className="truncate text-ui font-medium text-ink">{who}</div>
        <div className="break-words text-meta leading-snug text-ink-soft">
          {[when(c.at), c.provider_label, c.model, used].filter(Boolean).join(" · ")}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {c.failed && (
          <span data-tip={c.error ?? undefined}>
            <StatusChip tone="trail" label="Failed" />
          </span>
        )}
        {c.stopped ? (
          <span data-tip="Lockdown was on, so nothing was sent. It cost nothing.">
            <StatusChip tone="neutral" label="Stopped by Lockdown" />
          </span>
        ) : c.unknown ? (
          <StatusChip tone="neutral" label="Price unknown" />
        ) : c.cost !== null ? (
          <span className="text-ui tabular-nums text-ink">{money(c.cost)}</span>
        ) : null}
      </div>
    </li>
  );
}

export default function AIUsage() {
  const { data } = useLive<Usage>(api.aiUsage);
  if (!data) return null;
  const { month, last_30_days: days, recent } = data;
  const monthName = new Date(month.start).toLocaleDateString(undefined, { month: "long" });
  const checked = formatDate(data.prices_checked);
  return (
    <Section
      icon={<ReceiptIcon size={16} />}
      title="AI usage"
      blurb={`What the AI calls cost, at the providers' published prices (checked ${checked}). Local models cost nothing.`}
      delay={60}
    >
      {recent.length === 0 ? (
        <p className="py-3.5 text-hint text-ink-soft">No AI calls yet. Each one will show here with what it cost.</p>
      ) : (
        <>
          <ControlRow
            label={`This month (${monthName})`}
            hint={month.unknown ? `${counts(month)}. Calls at an unknown price aren’t in the total.` : counts(month)}
          >
            <span className="shrink-0 text-heading font-semibold tabular-nums text-ink">{money(month.cost)}</span>
          </ControlRow>
          <div className="py-3.5">
            <div className="flex items-baseline justify-between gap-5">
              <div className="min-w-0">
                <span className="block text-label font-medium leading-5 text-ink">Last 30 days</span>
                <span className="mt-0.5 block text-hint leading-[1.45] text-ink-soft">{counts(days)}</span>
              </div>
              <span className="shrink-0 text-label font-medium tabular-nums text-ink">{money(days.cost)}</span>
            </div>
            {days.calls > 0 && (
              <div className="mt-3 grid gap-x-8 gap-y-4 sm:grid-cols-2">
                <Breakdown title="By provider" rows={days.by_provider} />
                <Breakdown title="By module" rows={days.by_module} />
              </div>
            )}
          </div>
          <div className="py-3.5">
            <span className="block text-label font-medium leading-5 text-ink">Latest calls</span>
            <ul className="mt-1 divide-y divide-line">
              {recent.map((c, i) => (
                <Call key={`${c.at}-${i}`} c={c} />
              ))}
            </ul>
          </div>
        </>
      )}
    </Section>
  );
}
