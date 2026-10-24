// Small pieces shared by the module's screens.
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Avatar as CoreAvatar } from "@core/components/blocks";
import { LockIcon } from "@core/components/icons";
import type { EntityKind } from "./api";
import { pictureUrl, usePictures } from "./pictures";

export { Empty, Tags } from "@core/components/blocks";

export function useDebounced<T>(value: T, ms = 200): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** The host's Avatar, round for people and rounded-square for everything else. With the record's `id`, its picture
 *  shows in place of the initials when it has one. */
export function Avatar({ name, kind = "person", size = 36, id }: { name: string; kind?: EntityKind; size?: number; id?: string }) {
  const pictures = usePictures();
  const version = id ? pictures[id] : undefined;
  if (id && version) {
    return (
      <img
        src={pictureUrl(id, version)}
        alt=""
        aria-hidden="true"
        width={size}
        height={size}
        loading="lazy"
        className={`shrink-0 bg-surface-subtle object-cover ${kind === "person" ? "rounded-full" : "rounded-sm"}`}
        style={{ width: size, height: size }}
      />
    );
  }
  return <CoreAvatar name={name} round={kind === "person"} size={size} />;
}

/** Says why a feature is off while Lockdown is on (the server's sentence), or nothing when it isn't. */
export function LockedNote({ why }: { why: string | null | undefined }) {
  if (!why) return null;
  return (
    <p className="flex items-start gap-1.5 py-3.5 text-hint text-ink-soft">
      <LockIcon size={16} className="shrink-0" /> {why}
    </p>
  );
}

/** "Founder · Acme", without repeating the organization when the title already names it. */
export function roleLine(title: string | null | undefined, org: string | null | undefined): string {
  if (title && org && title.toLowerCase().includes(org.toLowerCase())) return title;
  return [title, org].filter(Boolean).join(" · ");
}

export const KIND_LABEL: Record<EntityKind, { one: string; many: string; path: string }> = {
  person: { one: "Person", many: "People", path: "crm/people" },
  organization: { one: "Organization", many: "Organizations", path: "crm/organizations" },
  meeting: { one: "Meeting", many: "Meetings", path: "crm/meetings" },
  document: { one: "Document", many: "Documents", path: "crm/documents" },
  topic: { one: "Topic", many: "Topics", path: "crm/topics" },
};

export const ATTRIBUTE_FIELDS: Record<EntityKind, { key: string; label: string; type?: string }[]> = {
  person: [
    { key: "title", label: "Title" },
    { key: "email", label: "Email", type: "email" },
    { key: "phone", label: "Phone", type: "tel" },
    { key: "location", label: "Location" },
    { key: "linkedin_url", label: "LinkedIn URL", type: "url" },
  ],
  organization: [
    { key: "industry", label: "Industry" },
    { key: "website", label: "Website" },
    { key: "domain", label: "Domain" },
    { key: "location", label: "Location" },
  ],
  meeting: [{ key: "location", label: "Location" }],
  document: [
    { key: "doc_type", label: "Type" },
    { key: "url", label: "URL", type: "url" },
  ],
  topic: [{ key: "description", label: "Description" }],
};

/** Five dots for how well you know someone (1 weak to 5 strong). Clickable when onChange is given. */
export function StrengthDots({ value, onChange }: { value: number; onChange?: (v: number) => void }) {
  return (
    <span className="inline-flex items-center gap-1" role="group" aria-label={`Strength ${value} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <button
          key={i}
          type="button"
          disabled={!onChange}
          onClick={() => onChange?.(i)}
          className={`h-2 w-2 rounded-full transition-transform ${i <= value ? "bg-forest" : "bg-line-strong"} ${onChange ? "cursor-pointer hover:scale-125" : "cursor-default"}`}
          aria-label={onChange ? `Set strength ${i}` : undefined}
          tabIndex={onChange ? 0 : -1}
        />
      ))}
    </span>
  );
}

/** A titled panel. `flush` lets rows run edge to edge (lists); otherwise the body is padded. */
export function Card({ title, action, flush, children }: { title: ReactNode; action?: ReactNode; flush?: boolean; children: ReactNode }) {
  return (
    <section className="panel overflow-hidden">
      <header className="flex items-center justify-between gap-3 px-5 pt-4 pb-1">
        <h2 className="text-heading font-semibold tracking-[-0.01em]">{title}</h2>
        {action}
      </header>
      <div className={flush ? "pt-1" : "px-5 pb-5 pt-2"}>{children}</div>
    </section>
  );
}

export function EntityLink({ entity, showSubtitle }: { entity: { id: string; name: string; subtitle?: string | null; is_self?: boolean }; showSubtitle?: boolean }) {
  return (
    <a href={`#/crm/e/${entity.id}`} className="inline-flex min-w-0 items-baseline gap-1.5 hover:underline">
      <span className="truncate font-medium">{entity.is_self ? `${entity.name} (you)` : entity.name}</span>
      {showSubtitle && entity.subtitle && <span className="truncate text-ink-soft">· {entity.subtitle}</span>}
    </a>
  );
}
