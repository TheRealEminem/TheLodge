// Larger pieces built from the design kit, shared by the host and every module.
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";
import type { Job, Linked, Person, PersonChoice } from "../api";
import { useLive } from "../live";
import { useShell } from "../shell";
import { initials } from "../format";
import { Badge } from "./illustrations";
import { AlertIcon, ChevronDownIcon, CloseIcon, PencilIcon, RefreshIcon, SearchIcon } from "./icons";
import { Spinner, StatusChip } from "./ui";

/** A settings-style section: a forest well, a heading with a one-line blurb, then a panel of rows. */
export function Section({
  icon,
  title,
  blurb,
  delay = 0,
  children,
}: {
  icon: ReactNode;
  title: string;
  blurb?: string;
  delay?: number;
  children: ReactNode;
}) {
  return (
    <section className="mb-10 animate-enter" style={{ animationDelay: `${delay}ms` } as CSSProperties}>
      <div className="mb-3 flex items-start gap-3 px-1">
        <span className="well well-forest">{icon}</span>
        <div className="min-w-0">
          <h2 className="text-heading font-semibold tracking-[-0.01em]">{title}</h2>
          {blurb && <p className="mt-0.5 text-ui leading-snug text-ink-soft">{blurb}</p>}
        </div>
      </div>
      <div className="panel divide-y divide-line px-5 sm:px-6">{children}</div>
    </section>
  );
}

/** A thing's background job as a chip, for list rows. Nothing when there's nothing to say. */
export function JobChip({ job }: { job: Job | null | undefined }) {
  if (!job || job.status === "done") return null;
  if (job.status === "running") return <StatusChip tone="sky" label={job.stage || "Working"} live />;
  if (job.status === "queued") return <StatusChip tone="neutral" label="Queued" />;
  if (job.status === "waiting") return <StatusChip tone="sun" label={job.wait_reason || "Needs you"} />;
  return <StatusChip tone="trail" label="Failed" />;
}

/** A thing's background job with what you can do about it: start it, go ahead anyway, or retry. */
export function JobStatus({ job, startLabel = "Start" }: { job: Job | null | undefined; startLabel?: string }) {
  const { toast } = useShell();
  const [busy, setBusy] = useState(false);
  if (!job || job.status === "done") return null;
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  if (job.status === "error") {
    return (
      <div className="flex animate-enter items-start gap-3 rounded-lg border border-trail/20 bg-trail-soft/70 p-4 text-label text-trail-deep">
        <AlertIcon size={18} className="mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="font-semibold">That didn't go through</div>
          <div className="mt-0.5 break-words opacity-90">{job.error}</div>
        </div>
        <button className="btn btn-sm btn-soft" disabled={busy} onClick={() => act(() => api.jobRetry(job.id))}>
          <RefreshIcon size={16} />
          Try again
        </button>
      </div>
    );
  }
  if (job.status === "waiting") {
    const needsYou = !job.wait_reason || job.wait_reason === "Needs you";
    return (
      <div className="flex animate-enter flex-wrap items-center gap-3">
        <StatusChip tone="sun" label={job.wait_reason || "Needs you"} />
        <button
          className={`btn btn-sm ${needsYou ? "btn-sun" : "btn-soft"}`}
          disabled={busy}
          onClick={() => act(() => api.jobGo(job.id, !needsYou))}
        >
          {needsYou ? startLabel : "Go ahead anyway"}
        </button>
      </div>
    );
  }
  return (
    <div className="flex animate-fade-in items-center gap-2 text-ui text-ink-soft">
      <Spinner className="text-sky" />
      {job.status === "queued" ? "Queued" : job.stage || "Working…"}
    </div>
  );
}

/** Everything linked to `of` (a ref, "notes:<id>"), from any module, each described by its own module. */
export function LinkedList({ of, title = "Linked" }: { of: string; title?: string }) {
  const { app } = useShell();
  const { data } = useLive(() => api.links(of), [of]);
  if (!data?.length) return null;
  const moduleName = (id: string) => app.modules.find((m) => m.id === id)?.name ?? id;
  return (
    <section className="mt-10 animate-enter">
      <h2 className="eyebrow mb-2 px-1">{title}</h2>
      <div className="panel divide-y divide-line px-2">
        {data.map((l: Linked) => (
          <a key={l.ref + l.kind} href={l.href} className="flex items-center justify-between gap-3 rounded-md px-3 py-3 transition-colors hover:bg-forest/[.04]">
            <span className="min-w-0 truncate text-label">{l.title}</span>
            <span className="shrink-0 text-meta text-ink-soft">{moduleName(l.module)}</span>
          </a>
        ))}
      </div>
    </section>
  );
}

/** A text setting that saves when you leave the field or press Return. */
export function TextSetting({
  value,
  onSave,
  placeholder,
  mono,
  className = "w-full sm:w-64",
  label,
}: {
  value: string;
  onSave: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
  className?: string;
  label: string;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => draft !== value && onSave(draft.trim());
  return (
    <input
      aria-label={label}
      className={`field ${mono ? "font-mono text-hint" : ""} ${className}`}
      value={draft}
      placeholder={placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

/** An API key: never shown again once saved, only a hint of its end. */
export function SecretSetting({ hint, onSave, label }: { hint: string | null | undefined; onSave: (v: string) => void; label: string }) {
  const [draft, setDraft] = useState("");
  return (
    <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:flex-nowrap">
      <input
        type="password"
        aria-label={label}
        autoComplete="off"
        className="field min-w-0 flex-1 font-mono text-hint sm:w-60 sm:flex-none"
        placeholder={hint ? `Saved (${hint})` : "Paste a key"}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && draft.trim()) {
            onSave(draft.trim());
            setDraft("");
          }
        }}
      />
      <button
        className="btn btn-sm btn-soft"
        disabled={!draft.trim()}
        onClick={() => {
          onSave(draft.trim());
          setDraft("");
        }}
      >
        Save
      </button>
      {hint && !draft && (
        <button className="btn btn-sm btn-danger-ghost" onClick={() => onSave("")}>
          Remove
        </button>
      )}
    </div>
  );
}

/** Initials in a soft tile: round for people, rounded-square for everything else (an organization, a project). */
export function Avatar({ name, round = true, size = 36 }: { name: string; round?: boolean; size?: number }) {
  return (
    <span
      aria-hidden="true"
      className={`grid shrink-0 place-items-center bg-surface-subtle font-semibold text-ink-soft ${round ? "rounded-full" : "rounded-sm"}`}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.36) }}
    >
      {initials(name)}
    </span>
  );
}

/** Up to `max` tags as quiet chips. */
export function Tags({ tags, max = 2 }: { tags: string[]; max?: number }) {
  return (
    <>
      {tags.slice(0, max).map((t) => (
        <span key={t} className="chip bg-surface-subtle text-ink-soft">
          #{t}
        </span>
      ))}
    </>
  );
}

/** An empty list or page: the identity's badge around an icon, a title, and a line on what will appear here. */
export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="inset-surface px-4 py-12 text-center">
      <Badge>{icon}</Badge>
      <p className="mt-3 font-medium">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-sm text-ui text-ink-soft">{children}</p>}
    </div>
  );
}

// ── PersonPicker ───────────────────────────────────────────────────────

type PickerRow = { kind: "person"; person: Person } | { kind: "name"; name: string } | { kind: "none" };

/**
 * Choose someone from the people directory (GET /api/people): you first ("core:me"), then everyone a module or a
 * family app knows who matches, then "Use “Ana” as a name" for someone the app doesn't know (ref null). Gives back
 * {ref, name}, or null when cleared.
 */
export function PersonPicker({
  value,
  onChange,
  label,
  placeholder = "Choose someone",
  noneLabel = "No one",
  disabled,
  className = "",
}: {
  value: PersonChoice | null;
  onChange: (choice: PersonChoice | null) => void;
  label: string;
  placeholder?: string;
  /** The row that clears the choice; shown while something is chosen. */
  noneLabel?: string;
  disabled?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [found, setFound] = useState<{ people: Person[]; note: string | null } | null>(null);
  const [active, setActive] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const id = useId();

  const place = useCallback(() => {
    if (trigger.current) setRect(trigger.current.getBoundingClientRect());
  }, []);
  const close = useCallback((refocus = true) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  }, []);

  // Ask the directory as you type (a short pause first, and only the latest answer counts).
  useEffect(() => {
    if (!open) return;
    let alive = true;
    const t = setTimeout(() => {
      api.people(q.trim()).then(
        (r) => alive && (setFound(r), setActive(0)),
        () => alive && setFound({ people: [], note: "The people directory didn't answer. Type a name instead." }),
      );
    }, q ? 140 : 0);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [q, open]);

  useEffect(() => {
    if (!open) return;
    input.current?.focus({ preventScroll: true });
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!pop.current?.contains(t) && !trigger.current?.contains(t)) close(false);
    };
    const onScroll = (e: Event) => !pop.current?.contains(e.target as Node) && place();
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", place);
    };
  }, [open, place, close]);

  const typed = q.trim();
  const people = found?.people ?? [];
  const rows: PickerRow[] = [
    ...people.map((person) => ({ kind: "person" as const, person })),
    ...(typed && !people.some((p) => p.name.toLowerCase() === typed.toLowerCase()) ? [{ kind: "name" as const, name: typed }] : []),
    ...(value && !typed ? [{ kind: "none" as const }] : []),
  ];

  useEffect(() => {
    if (open) pop.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  const choose = (row: PickerRow | undefined) => {
    if (!row) return;
    onChange(row.kind === "person" ? { ref: row.person.ref, name: row.person.name } : row.kind === "name" ? { ref: null, name: row.name } : null);
    close();
  };
  const show = () => {
    place();
    setQ("");
    setFound(null);
    setOpen(true);
  };
  const onKey = (e: ReactKeyboardEvent) => {
    if (e.key === "ArrowDown") setActive((a) => Math.min(rows.length - 1, a + 1));
    else if (e.key === "ArrowUp") setActive((a) => Math.max(0, a - 1));
    else if (e.key === "Enter") choose(rows[active]);
    else if (e.key === "Escape") close();
    else if (e.key === "Tab") return close(false);
    else return;
    e.preventDefault();
  };

  let style: CSSProperties = {};
  if (rect) {
    const width = Math.min(Math.max(rect.width, 280), window.innerWidth - 16);
    const below = window.innerHeight - rect.bottom - 12;
    const up = below < 260 && rect.top > below;
    style = {
      left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
      width,
      maxHeight: Math.min(380, (up ? rect.top : below) - 8),
      transformOrigin: up ? "bottom" : "top",
      ...(up ? { bottom: window.innerHeight - rect.top + 6 } : { top: rect.bottom + 6 }),
    };
  }

  return (
    <>
      <button
        ref={trigger}
        type="button"
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={value ? `${label}: ${value.name}` : label}
        onClick={() => (open ? close(false) : show())}
        onKeyDown={(e) => {
          if (["ArrowDown", "Enter", " "].includes(e.key)) {
            e.preventDefault();
            show();
          }
        }}
        className={`field flex min-w-0 items-center gap-2 text-left ${className}`}
      >
        {value ? <PersonMark person={value} size={20} /> : null}
        <span className={`min-w-0 flex-1 truncate ${value ? "" : "text-ink-faint"}`}>{value ? personLabel(value) : placeholder}</span>
        <ChevronDownIcon size={16} className={`shrink-0 text-ink-faint transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
      </button>
      {open &&
        rect &&
        createPortal(
          <div
            ref={pop}
            role="dialog"
            aria-label={label}
            style={style}
            className="fixed z-[60] flex animate-pop flex-col overflow-hidden rounded-md border border-line bg-surface shadow-lg"
          >
            <div className="flex items-center gap-2 border-b border-line px-3">
              <SearchIcon size={16} className="shrink-0 text-ink-faint" />
              <input
                ref={input}
                role="combobox"
                aria-expanded="true"
                aria-controls={id}
                aria-activedescendant={rows.length ? `${id}-${active}` : undefined}
                aria-autocomplete="list"
                aria-label={`Search for ${label.toLowerCase()}`}
                className="min-w-0 flex-1 bg-transparent py-2.5 text-ui text-ink outline-none placeholder:text-ink-faint"
                placeholder="Type a name"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={onKey}
              />
            </div>
            <ul id={id} role="listbox" aria-label={label} className="min-h-0 flex-1 overflow-y-auto p-1">
              {!found && <li className="px-2.5 py-2 text-ui text-ink-soft">Looking…</li>}
              {found && !rows.length && <li className="px-2.5 py-2 text-ui text-ink-soft">Type a name to find someone.</li>}
              {rows.map((row, i) => (
                <li
                  key={row.kind === "person" ? row.person.ref : row.kind}
                  id={`${id}-${i}`}
                  data-i={i}
                  role="option"
                  aria-selected={row.kind === "person" ? value?.ref === row.person.ref : row.kind === "none" ? false : value?.name === row.name && !value.ref}
                  onPointerMove={() => active !== i && setActive(i)}
                  onClick={() => choose(row)}
                  className={`flex cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-2 text-ui leading-5 transition-colors duration-100 ${
                    i === active ? "bg-forest/[.07]" : ""
                  }`}
                >
                  {row.kind === "person" ? (
                    <>
                      <PersonMark person={row.person} size={26} />
                      <span className="min-w-0 flex-1">
                        <span className={`block truncate ${value?.ref === row.person.ref ? "font-medium" : ""}`}>{personLabel(row.person)}</span>
                        {(row.person.detail || row.person.email) && (
                          <span className="block truncate text-meta text-ink-soft">
                            {row.person.ref === "core:me" ? row.person.email || "You" : [row.person.detail, row.person.email].filter(Boolean).join(" · ")}
                          </span>
                        )}
                      </span>
                    </>
                  ) : row.kind === "name" ? (
                    <>
                      <span className="grid h-[26px] w-[26px] shrink-0 place-items-center rounded-full border border-dashed border-line-strong text-ink-soft">
                        <PencilIcon size={13} />
                      </span>
                      <span className="min-w-0 flex-1 truncate">Use “{row.name}” as a name</span>
                    </>
                  ) : (
                    <>
                      <span className="grid h-[26px] w-[26px] shrink-0 place-items-center rounded-full bg-surface-subtle text-ink-soft">
                        <CloseIcon size={13} />
                      </span>
                      <span className="min-w-0 flex-1 truncate text-ink-soft">{noneLabel}</span>
                    </>
                  )}
                </li>
              ))}
            </ul>
            {found?.note && <p className="border-t border-line px-3 py-2 text-meta text-ink-soft">{found.note}</p>}
          </div>,
          document.body,
        )}
    </>
  );
}

const personLabel = (p: { ref: string | null; name: string }) => (p.ref === "core:me" && p.name !== "You" ? `${p.name} (you)` : p.name);

/** A person's initials: on sky for you (You = sky), quiet for everyone else, dashed for a name the app doesn't know. */
function PersonMark({ person, size }: { person: { ref: string | null; name: string }; size: number }) {
  if (person.ref === "core:me") {
    return (
      <span
        aria-hidden="true"
        className="grid shrink-0 place-items-center rounded-full bg-sky-soft font-semibold text-sky-deep"
        style={{ width: size, height: size, fontSize: Math.round(size * 0.38) }}
      >
        {person.name === "You" ? "Y" : initials(person.name)}
      </span>
    );
  }
  if (!person.ref) {
    return (
      <span
        aria-hidden="true"
        className="grid shrink-0 place-items-center rounded-full border border-dashed border-line-strong font-semibold text-ink-soft"
        style={{ width: size, height: size, fontSize: Math.round(size * 0.36) }}
      >
        {initials(person.name)}
      </span>
    );
  }
  return <Avatar name={person.name} size={size} />;
}
