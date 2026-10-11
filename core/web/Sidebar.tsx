// The sidebar: the app's mark, the main action, search across every module, and each module's navigation.
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import type { SearchGroup } from "./api";
import { CloseIcon, HomeIcon, SearchIcon, SlidersIcon } from "./components/icons";
import { Logo } from "./components/illustrations";
import type { ModuleWeb } from "./registry";
import { useShell } from "./shell";

function NavLink({ icon, label, href, active, badge }: { icon: ReactNode; label: string; href: string; active: boolean; badge?: ReactNode }) {
  return (
    <a
      href={href}
      aria-current={active ? "page" : undefined}
      className={`flex h-9 w-full items-center gap-2.5 rounded-md px-2.5 text-ui font-medium transition-[background-color,color,transform] duration-150 ease-out hover:translate-x-px ${
        active ? "bg-surface text-ink shadow-sm ring-1 ring-line" : "text-ink-soft hover:bg-forest/[.05] hover:text-ink"
      }`}
    >
      <span className={`transition-colors ${active ? "text-forest" : ""}`}>{icon}</span>
      <span className="flex-1 text-left">{label}</span>
      {badge}
    </a>
  );
}

/** A count for a nav item (open tasks…), styled the family way. Modules render it from their badge component. */
export function NavCount({ n }: { n: number | null | undefined }) {
  if (!n) return null;
  return (
    <span className="min-w-[20px] rounded-full bg-forest/10 px-1.5 py-0.5 text-center text-caption font-semibold tabular-nums text-forest-deep">
      {n}
    </span>
  );
}

export default function Sidebar({ modules, path, opaque }: { modules: ModuleWeb[]; path: string; opaque?: boolean }) {
  const { app } = useShell();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchGroup[] | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const primary = modules.find((m) => m.primary)?.primary;
  const mac = navigator.platform.toLowerCase().includes("mac");
  const showHome = modules.length > 1 || modules.some((m) => m.home);
  const under = (p: string) => path === p || path.startsWith(p + "/");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const q = query.trim();
    if (!q) return setResults(null);
    const t = setTimeout(() => api.search(q).then(setResults, () => setResults([])), 160);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => setQuery(""), [path]);

  return (
    <aside className={`chrome relative z-10 flex h-full w-[288px] shrink-0 flex-col border-r border-line shadow-chrome ${opaque ? "chrome-opaque" : ""}`}>
      <a href="#/" className="flex items-center gap-3 px-6 pb-5 pt-7">
        <Logo size={38} />
        <div className="min-w-0">
          <div className="font-display text-wordmark font-semibold leading-none tracking-[-0.02em] text-ink">{app.name}</div>
          {app.tagline && <div className="mt-1.5 text-caption leading-none text-ink-faint">{app.tagline}</div>}
        </div>
      </a>

      <div className="px-4">
        {primary && (
          <button onClick={() => void primary.run()} className="group btn btn-primary mb-4 h-11 w-full rounded-md text-label font-semibold">
            <span className="transition-transform duration-200 ease-spring group-hover:-rotate-6 group-hover:scale-110">{primary.icon}</span>
            {primary.label}
          </button>
        )}
        <div className="relative">
          <SearchIcon size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setQuery("")}
            placeholder="Search"
            aria-label="Search everything"
            className="field h-9 w-full border-transparent bg-forest/[.045] py-0 pl-9 pr-12 shadow-none hover:border-line focus:bg-surface"
          />
          <span className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center">
            {query ? (
              <button onClick={() => setQuery("")} className="icon-btn h-6 w-6" aria-label="Clear search">
                <CloseIcon size={14} />
              </button>
            ) : (
              <kbd className="kbd pointer-events-none [@media(pointer:coarse)]:hidden">{mac ? "⌘K" : "Ctrl K"}</kbd>
            )}
          </span>
        </div>
      </div>

      {results ? (
        <nav className="fade-edges-y mt-3 flex-1 overflow-y-auto px-3 pb-4 pt-1" aria-label="Search results">
          {results.length === 0 && <p className="px-3 pt-3 text-hint text-ink-soft">Nothing matches “{query.trim()}”.</p>}
          {results.map((g) => (
            <section key={g.module} className="animate-fade-in">
              <h3 className="eyebrow px-3 pb-1.5 pt-3">{g.module_name}</h3>
              {g.hits.map((h) => (
                <a key={h.ref} href={h.href} className="mb-0.5 block rounded-md px-3 py-2 transition-colors duration-150 hover:bg-forest/[.05]">
                  <div className="truncate text-ui font-medium">{h.title}</div>
                  {h.snippet && <div className="mt-0.5 line-clamp-2 text-meta leading-snug text-ink-soft">{h.snippet}</div>}
                </a>
              ))}
            </section>
          ))}
        </nav>
      ) : (
        <nav className="mt-3 flex-1 space-y-0.5 overflow-y-auto px-3" aria-label="Sections">
          {showHome && <NavLink icon={<HomeIcon size={16} />} label="Home" href="#/" active={path === ""} />}
          {modules.flatMap((m) =>
            (m.nav ?? []).map((item) => {
              const Badge = item.badge;
              return (
                <NavLink
                  key={m.id + item.path}
                  icon={item.icon}
                  label={item.label}
                  href={`#/${item.path}`}
                  active={under(item.path)}
                  badge={Badge ? <Badge /> : undefined}
                />
              );
            }),
          )}
        </nav>
      )}

      <div className="border-t border-line px-3 py-2">
        <NavLink icon={<SlidersIcon size={16} />} label="Settings" href="#/settings" active={path === "settings"} />
      </div>
    </aside>
  );
}
