// Lockdown (core/server/lockdown.py): the status the app's chrome reads, and the sign it shows while Lockdown is on. The
// switch itself is Settings → Privacy.
import { Shield } from "lucide-react";
import { api } from "../api";
import type { LockdownStatus } from "../api";
import { icon } from "../components/icons";
import { useLive } from "../live";

export const ShieldIcon = icon(Shield);

export function useLockdown() {
  return useLive<LockdownStatus>(api.lockdown).data;
}

function waiting(n: number) {
  return `${n} ${n === 1 ? "thing waits" : "things wait"} for it to be off`;
}

/** The sign in the app's chrome while Lockdown is on: the sidebar's, or a small one for the top bar of a narrow window. */
export function LockdownSign({ compact = false }: { compact?: boolean }) {
  const status = useLockdown();
  if (!status?.on) return null;
  const tip = `Nothing leaves this computer.${status.parked ? ` ${waiting(status.parked)}.` : ""} Open Settings to turn it off.`;
  if (compact) {
    return (
      <a href="#/settings?section=lockdown" className="chip ml-auto bg-sun-soft text-sun-deep" data-tip={tip}>
        <ShieldIcon size={14} />
        Lockdown
      </a>
    );
  }
  return (
    <a
      href="#/settings?section=lockdown"
      data-tip={tip}
      className="mx-4 mb-4 flex animate-enter items-center gap-2.5 rounded-md border border-sun/30 bg-sun-soft/70 px-3 py-2 text-ui font-medium text-sun-deep transition-colors hover:bg-sun-soft"
    >
      <ShieldIcon size={16} />
      <span className="flex-1">Lockdown is on</span>
      {status.parked > 0 && <span className="text-meta tabular-nums">{status.parked} waiting</span>}
    </a>
  );
}
