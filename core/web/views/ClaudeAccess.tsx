// Settings → Claude: Claude Code and Claude Desktop use the app through its MCP server (core/server/mcp.py). Off until
// you make a token; the token is shown once, inside the command and the config to copy, and never again.
import { useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import type { McpSetup, McpStatus } from "../api";
import { Section } from "../components/blocks";
import { KeyIcon, LaptopIcon, PowerIcon, RefreshIcon, SparkleIcon, icon } from "../components/icons";
import { ControlRow, CopyButton, Spinner } from "../components/ui";
import { useLive } from "../live";
import { useShell } from "../shell";
import { SquareTerminal } from "lucide-react";

const TerminalIcon = icon(SquareTerminal);

function Snippet({ icon, label, hint, text }: { icon: ReactNode; label: string; hint: string; text: string }) {
  return (
    <div className="py-3.5">
      <div className="flex items-start justify-between gap-5">
        <div className="flex min-w-0 items-center gap-3.5">
          <span className="well">{icon}</span>
          <div className="min-w-0">
            <span className="block text-label font-medium leading-5 text-ink">{label}</span>
            <span className="mt-0.5 block text-hint leading-[1.45] text-ink-soft">{hint}</span>
          </div>
        </div>
        <div className="shrink-0">
          <CopyButton text={text} />
        </div>
      </div>
      <pre className="inset-surface mt-3 max-h-56 overflow-auto whitespace-pre-wrap break-all px-3 py-2.5 font-mono text-meta leading-relaxed text-ink">
        {text}
      </pre>
    </div>
  );
}

export default function ClaudeAccess() {
  const { app, toast, confirm } = useShell();
  const { data } = useLive<McpStatus>(api.mcp);
  const [setup, setSetup] = useState<McpSetup | null>(null);
  const [busy, setBusy] = useState(false);
  if (!data) return null;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  const makeToken = () =>
    run(async () => {
      if (data.on) {
        const ok = await confirm({
          title: "Make a new token?",
          body: "Claude Code and Claude Desktop stop reaching the app until you paste the new command and config in.",
          confirmLabel: "Make a new token",
        });
        if (!ok) return;
      }
      setSetup((await api.mcpToken()).setup);
    });
  const turnOff = () =>
    run(async () => {
      const ok = await confirm({
        title: "Turn Claude's access off?",
        body: `Claude Code and Claude Desktop can't reach ${app.name} until you turn it on again, with a new token.`,
        confirmLabel: "Turn off",
        tone: "danger",
      });
      if (!ok) return;
      await api.mcpOff();
      setSetup(null);
    });

  return (
    <Section
      icon={<SparkleIcon size={16} />}
      title="Claude"
      blurb={`Claude Code and Claude Desktop can use ${app.name}. They can read and add here, and propose; anything that needs your yes still waits for you.`}
      delay={90}
    >
      {!data.on ? (
        <ControlRow label={`Let Claude use ${app.name}`} hint={`Off: Claude can't reach ${app.name}. On: it signs in with a token, on this Mac only.`} wrap>
          <button className="btn btn-sm btn-soft" disabled={busy} onClick={() => void makeToken()}>
            {busy ? <Spinner /> : <PowerIcon size={16} />}
            Turn on
          </button>
        </ControlRow>
      ) : (
        <>
          {setup ? (
            <>
              <Snippet
                icon={<TerminalIcon size={16} />}
                label="Claude Code"
                hint="Run this once in Terminal. Copy it now: the token in it isn't shown again."
                text={setup.claude_code}
              />
              <Snippet
                icon={<LaptopIcon size={16} />}
                label="Claude Desktop"
                hint="Settings → Developer → Edit Config: add this to claude_desktop_config.json (inside its mcpServers, if it has one), then quit and reopen Claude."
                text={setup.claude_desktop}
              />
            </>
          ) : null}
          <ControlRow
            icon={<KeyIcon size={16} />}
            label="On"
            hint={
              <>
                Claude signs in with the token ending <span className="whitespace-nowrap">{data.hint}</span>. To set Claude up again, make a new token; the old one stops
                working.
              </>
            }
            wrap
          >
            <div className="flex flex-wrap gap-2">
              <button className="btn btn-sm btn-soft" disabled={busy} onClick={() => void makeToken()}>
                {busy ? <Spinner /> : <RefreshIcon size={16} />}
                Make a new token
              </button>
              <button className="btn btn-sm btn-danger-ghost" disabled={busy} onClick={() => void turnOff()}>
                Turn off
              </button>
            </div>
          </ControlRow>
        </>
      )}
      {data.tools.length > 0 && (
        <ControlRow label="What it can do" hint={`${data.tools.map((t) => t.title).join(" · ")}. Nothing it does is sent anywhere else.`} />
      )}
    </Section>
  );
}
