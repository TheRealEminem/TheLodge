// A field that saves as you leave it, used on the task and project pages.
import { useEffect, useState } from "react";

/** A field that saves when you leave it or press Return (Escape puts it back). */
export function Field({ value, onSave, label, placeholder, className = "", type = "text", bare = false }: {
  value: string;
  onSave: (v: string) => void;
  label: string;
  placeholder?: string;
  className?: string;
  type?: "text" | "date";
  bare?: boolean;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <input
      type={type}
      aria-label={label}
      className={bare ? className : `field ${className}`}
      value={draft}
      placeholder={placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => draft !== value && onSave(draft)}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") {
          setDraft(value);
          (e.target as HTMLInputElement).blur();
        }
      }}
    />
  );
}
