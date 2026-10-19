import { useState } from "react";
import { api } from "../api";
import { KeyIcon } from "../components/icons";
import { Ambient, Scene } from "../components/illustrations";
import { signInTitle } from "@identity/copy";

/** Only for installs that set an access token (a server); local apps never see this. */
export default function Login({ onDone, dusk }: { onDone: () => void; dusk: boolean }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.login(token);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="relative flex h-full flex-col items-center justify-center p-5 text-center">
      <Ambient />
      <div className="relative w-full max-w-[440px] animate-enter">
        <div className="art-frame h-44">
          <Scene dusk={dusk} className="h-full w-full" />
        </div>
        <h1 className="page-title mt-6">{signInTitle}</h1>
        <p className="mt-2 text-body leading-relaxed text-ink-soft">Enter the access token for this server.</p>
        <form
          className="mt-6 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <input type="password" className="field h-10 flex-1" placeholder="Access token" value={token} onChange={(e) => setToken(e.target.value)} autoFocus />
          <button className="btn btn-md btn-primary" disabled={!token || busy}>
            <KeyIcon size={16} />
            Sign in
          </button>
        </form>
        {error && <p className="mt-3 text-hint text-trail-deep">{error}</p>}
      </div>
    </div>
  );
}
