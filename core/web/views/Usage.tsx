// Settings → AI → Usage: a quiet running count of what AI has been asked to do, there when you look for it.
// Nothing here limits anything; the only interruption elsewhere is a warning before a job that would cost a lot.
import { useState } from "react";
import { api } from "../api";
import { ChevronDownIcon } from "../components/icons";
import { ControlRow } from "../components/ui";
import { useLive } from "../live";
import { useSettings } from "../shell";

export const dollars = (n: number) => (n === 0 ? "$0" : n < 0.01 ? "under 1¢" : n < 1 ? `${Math.round(n * 100)}¢` : `$${n.toFixed(2)}`);
const count = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n));

function Bar({ share }: { share: number }) {
  return (
    <span className="block h-1.5 w-full overflow-hidden rounded-full bg-line">
      <span className="block h-full rounded-full bg-forest" style={{ width: `${Math.max(2, Math.round(share * 100))}%` }} />
    </span>
  );
}

/** Rows for the AI section: the month's figure with a Details toggle, and the limit for warnings. */
export function UsageRows() {
  const { data } = useLive(api.usage, []);
  const { get, save } = useSettings();
  const [open, setOpen] = useState(false);
  const [limit, setLimit] = useState<string | null>(null);
  if (!data) return null;
  const { this_month: now, last_month: last } = data;
  const top = Math.max(...data.by_source.map((s) => s.cost || s.calls), 0.0001);
  const dayTop = Math.max(...data.by_day.map((d) => d.cost || d.calls), 0.0001);
  const saveLimit = () => {
    const n = Math.round(Number(limit));
    if (limit !== null && Number.isFinite(n) && n >= 0) void save({ "ai.warn_over": n });
    setLimit(null);
  };
  const anyCost = data.by_source.some((s) => s.cost > 0);
  return (
    <>
      <ControlRow
        label="Usage"
        hint={now.calls === 0 ? "Nothing yet this month." : `About ${dollars(now.cost)} this month, ${now.calls} request${now.calls === 1 ? "" : "s"}${now.unpriced ? " (some not priced)" : ""}. Just a count: nothing is limited.`}
      >
        <button className="btn btn-sm btn-ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
          Details <ChevronDownIcon size={16} className={open ? "rotate-180" : ""} />
        </button>
      </ControlRow>
      {open && (
        <div className="space-y-5 py-3.5 text-ui">
          <p className="text-ink-soft">
            This month about <span className="font-medium text-ink">{dollars(now.cost)}</span>, {count(now.tokens)} tokens.
            Last month {dollars(last.cost)}, {last.calls} request{last.calls === 1 ? "" : "s"}.
          </p>
          {data.by_source.length > 0 && (
            <div>
              <p className="mb-2 text-label font-medium">What it went to</p>
              <ul className="space-y-2">
                {data.by_source.map((s) => (
                  <li key={s.name}>
                    <span className="flex items-baseline justify-between gap-3">
                      <span className="min-w-0 truncate">{s.name}</span>
                      <span className="shrink-0 text-hint tabular-nums text-ink-soft">{s.calls} request{s.calls === 1 ? "" : "s"} · {dollars(s.cost)}</span>
                    </span>
                    <Bar share={(anyCost ? s.cost : s.calls) / (anyCost ? top : Math.max(top, 1))} />
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.by_day.length > 1 && (
            <div>
              <p className="mb-2 text-label font-medium">Day by day</p>
              <div className="flex h-12 items-end gap-1" role="img" aria-label="Estimated cost per day this month">
                {data.by_day.map((d) => (
                  <span key={d.day} title={`${d.day}: ${dollars(d.cost)}, ${d.calls} request${d.calls === 1 ? "" : "s"}`}
                    className="min-w-[3px] flex-1 rounded-sm bg-forest" style={{ height: `${Math.max(6, ((d.cost || d.calls) / dayTop) * 100)}%` }} />
                ))}
              </div>
            </div>
          )}
          {data.by_model.length > 0 && (
            <div>
              <p className="mb-2 text-label font-medium">Which AI</p>
              <ul className="space-y-1.5">
                {data.by_model.map((m) => (
                  <li key={`${m.provider}:${m.model}`} className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className="min-w-0 truncate">{m.model}</span>
                    <span className="text-hint tabular-nums text-ink-soft">
                      {m.calls}× · {count(m.tokens_in + m.tokens_out)} tokens · {m.local ? "free, on this Mac" : m.priced ? dollars(m.cost) : "price unknown"}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-hint text-ink-soft">
            Token counts are what each AI reported. Dollars are estimates from list prices as of {data.prices_as_of}, so your bill may differ a little.
            Local models are free.
          </p>
        </div>
      )}
      {open && (
        <ControlRow label="Warn before big jobs" hint={`Only a job estimated at this much or more asks first, such as researching a lot of people at once. 0 turns warnings off.`}>
          <span className="inline-flex items-center gap-1.5 text-ui">
            $<input className="field h-9 w-20 px-2 tabular-nums" inputMode="numeric" aria-label="Warn when a job is estimated at or over, in dollars"
              value={limit ?? String(get<number>("ai.warn_over") ?? data.warn_over)} onChange={(e) => setLimit(e.target.value)}
              onBlur={saveLimit} onKeyDown={(e) => e.key === "Enter" && saveLimit()} />
          </span>
        </ControlRow>
      )}
    </>
  );
}
