// The search box at the top of Home: type part of a name, role, organization or tag, and open their profile.
// ↑ and ↓ move through the matches, Return opens one, Escape clears, and "/" anywhere on Home jumps back here.
import { useEffect, useId, useRef, useState } from "react";
import { SearchIcon } from "@core/components/icons";
import { Spinner } from "@core/components/ui";
import { navigate } from "@core/router";
import { crmApi } from "./api";
import type { PersonRow } from "./api";
import { Avatar, roleLine } from "./bits";
import { TierBadge } from "./tier";

const LIMIT = 7;
const typing = (t: EventTarget | null) => t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));

export default function PersonFinder() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<PersonRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const list = useId();

  useEffect(() => {
    const term = q.trim();
    if (!term) {
      setRows(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    let alive = true;
    const t = setTimeout(
      () =>
        crmApi.people({ q: term, limit: LIMIT, sort: "match" }).then(
          (page) => {
            if (!alive) return;
            setRows(page.items);
            setTotal(page.total);
            setActive(0);
            setLoading(false);
          },
          () => alive && (setRows([]), setLoading(false)),
        ),
      110,
    );
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [q]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && !e.metaKey && !e.ctrlKey && !typing(e.target)) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Ready to type as soon as Home opens (with a mouse or trackpad; on touch it would pop up the keyboard), without
  // scrolling the page past the picture to get there.
  useEffect(() => {
    if (window.matchMedia?.("(pointer: fine)").matches) input.current?.focus({ preventScroll: true });
  }, []);

  const open = (r: PersonRow) => navigate(`crm/e/${r.person.id}`);
  const shown = rows ?? [];
  const optionId = (i: number) => `${list}-${i}`;

  return (
    <div className="relative z-20 mb-8 animate-enter">
      <SearchIcon size={20} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-faint" />
      <input
        ref={input}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && shown.length) {
            e.preventDefault();
            setActive((a) => (a + 1) % shown.length);
          } else if (e.key === "ArrowUp" && shown.length) {
            e.preventDefault();
            setActive((a) => (a - 1 + shown.length) % shown.length);
          } else if (e.key === "Enter" && shown[active]) {
            e.preventDefault();
            open(shown[active]);
          } else if (e.key === "Escape") {
            setQ("");
          }
        }}
        role="combobox"
        aria-expanded={rows !== null}
        aria-controls={list}
        aria-activedescendant={shown.length ? optionId(active) : undefined}
        aria-autocomplete="list"
        aria-label="Find someone"
        placeholder="Find someone by name, role, organization or tag"
        className="field h-[52px] w-full rounded-lg pl-12 pr-12 text-body shadow-sm"
      />
      <span className="absolute right-4 top-1/2 flex -translate-y-1/2 items-center">
        {loading ? <Spinner className="text-ink-faint" /> : !q && <kbd className="kbd pointer-events-none [@media(pointer:coarse)]:hidden">/</kbd>}
      </span>

      {rows !== null && (
        <div id={list} role="listbox" aria-label="People" className="absolute inset-x-0 top-full mt-2 animate-pop overflow-hidden rounded-md border border-line bg-surface shadow-lg">
          {shown.length === 0 ? (
            <p className="px-4 py-3.5 text-ui text-ink-soft">No one matches “{q.trim()}”.</p>
          ) : (
            shown.map((r, i) => (
              <a
                key={r.person.id}
                id={optionId(i)}
                role="option"
                aria-selected={i === active}
                href={`#/crm/e/${r.person.id}`}
                onMouseMove={() => setActive(i)}
                className={`flex items-center gap-3.5 px-4 py-2.5 transition-colors duration-100 ${i === active ? "bg-forest/[.07]" : ""}`}
              >
                <Avatar name={r.person.name} size={34} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-label font-medium">{r.person.name}</div>
                  <div className="truncate text-hint text-ink-soft">{roleLine(r.title, r.org?.name) || r.location || " "}</div>
                </div>
                {!r.person.is_self && <TierBadge tier={r.connection.tier} />}
              </a>
            ))
          )}
          {total > shown.length && (
            <a href={`#/crm/people?q=${encodeURIComponent(q.trim())}`} className="block border-t border-line px-4 py-2.5 text-ui font-medium text-forest-deep hover:bg-forest/[.05]">
              All {total} matches
            </a>
          )}
        </div>
      )}
    </div>
  );
}
