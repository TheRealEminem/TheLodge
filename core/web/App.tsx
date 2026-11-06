// The host app: sign-in, the shell (sidebar, top bar on narrow windows, content column), and routing to the
// host's own views and every enabled module's views.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { AUTH_EVENT, api, setSystem, showInAppMenu } from "./api";
import type { AppInfo } from "./api";
import { BackIcon, ForwardIcon, MenuIcon } from "./components/icons";
import { Ambient, Logo } from "./components/illustrations";
import { Toast, TooltipLayer, useConfirm } from "./components/ui";
import type { ToastState } from "./components/ui";
import { startChangeFeed, useChanges } from "./live";
import { modulesFor } from "./registry";
import type { ModuleWeb, RouteProps } from "./registry";
import { match, navigate, useHistoryPlace, useRoute } from "./router";
import { ShellProvider } from "./shell";
import type { Shell } from "./shell";
import Sidebar from "./Sidebar";
import { useTheme } from "./theme";
import Home from "./views/Home";
import { LockdownSign } from "./views/Lockdown";
import Login from "./views/Login";
import NotFound from "./views/NotFound";
import Settings from "./views/Settings";
import Welcome from "./views/Welcome";
import type { ComponentType } from "react";

/** True when the sidebar sits beside the content rather than in a drawer. */
function useWide() {
  const query = "(min-width: 1024px)";
  const [wide, setWide] = useState(() => window.matchMedia?.(query).matches ?? true);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const on = () => setWide(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return wide;
}

/**
 * The first page of the day: when the app opens at Home, a module may show something else first (registry.start).
 * Asked once when the app loads, and again when the window comes back on a new day while it's still at Home; never
 * when the app opened somewhere else, or after you've moved on.
 */
function useStartPage(modules: ModuleWeb[]) {
  const askedOn = useRef<string | null>(null);
  useEffect(() => {
    const starters = modules.filter((m) => m.start);
    if (!starters.length) return;
    const atHome = () => location.hash.replace(/^#\/?/, "").split("?")[0] === "";
    const ask = async () => {
      const day = new Date().toDateString();
      if (askedOn.current === day) return;
      askedOn.current = day;
      if (!atHome()) return;
      for (const m of starters) {
        const to = await m.start!().catch(() => null);
        if (to) {
          if (atHome()) navigate(to);
          return;
        }
      }
    };
    void ask();
    const onShow = () => document.visibilityState === "visible" && void ask();
    document.addEventListener("visibilitychange", onShow);
    return () => document.removeEventListener("visibilitychange", onShow);
  }, [modules]);
}

const MAC = navigator.platform.toLowerCase().includes("mac");
const typing = (t: EventTarget | null) => t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));

/** Back and Forward through where you've been, with the keys a browser uses: ⌘[ and ⌘] on a Mac, Alt+arrows elsewhere. */
function BackForward({ canBack, canForward }: { canBack: boolean; canForward: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const back = MAC ? e.metaKey && e.key === "[" : e.altKey && e.key === "ArrowLeft" && !typing(e.target);
      const forward = MAC ? e.metaKey && e.key === "]" : e.altKey && e.key === "ArrowRight" && !typing(e.target);
      if (!back && !forward) return;
      e.preventDefault();
      if (back) history.back();
      else history.forward();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="flex items-center gap-0.5">
      <button className="btn btn-sm btn-ghost px-2" disabled={!canBack} aria-label="Back" data-tip={MAC ? "Back (⌘[)" : "Back (Alt+←)"} onClick={() => history.back()}>
        <BackIcon size={16} /> <span className="hidden sm:inline">Back</span>
      </button>
      <button className="icon-btn h-8 w-8" disabled={!canForward} aria-label="Forward" data-tip={MAC ? "Forward (⌘])" : "Forward (Alt+→)"} onClick={() => history.forward()}>
        <ForwardIcon size={16} />
      </button>
    </div>
  );
}

/** Each place in your history keeps its scroll: going back lands where you were, once the page has loaded that far. */
function useScrollMemory(at: number, returned: () => boolean) {
  const main = useRef<HTMLElement>(null);
  const tops = useRef(new Map<number, number>());
  const restoring = useRef(false);
  useLayoutEffect(() => {
    const el = main.current;
    if (!el) return;
    const target = returned() ? tops.current.get(at) ?? 0 : 0;
    el.scrollTop = target;
    if (!target) return;
    restoring.current = true;
    const stop = () => { restoring.current = false; };
    const give = window.setInterval(() => {
      el.scrollTop = target;
      if (Math.abs(el.scrollTop - target) < 2) { stop(); window.clearInterval(give); }
    }, 60);
    const end = window.setTimeout(() => { stop(); window.clearInterval(give); }, 2000);
    el.addEventListener("wheel", stop, { once: true, passive: true });
    return () => {
      stop();
      window.clearInterval(give);
      window.clearTimeout(end);
      el.removeEventListener("wheel", stop);
    };
  }, [at, returned]);
  const onScroll = useCallback(() => {
    if (!restoring.current && main.current) tops.current.set(at, main.current.scrollTop);
  }, [at]);
  return { main, onScroll };
}

function resolve(path: string, modules: ModuleWeb[]): { view: ComponentType<RouteProps>; params: Record<string, string>; wide?: boolean } {
  if (path === "") return { view: Home, params: {} };
  if (path === "settings") return { view: Settings as ComponentType<RouteProps>, params: {} };
  for (const m of modules) {
    for (const r of m.routes) {
      const params = match(r.path, path);
      if (params) return { view: r.view, params, wide: r.wide };
    }
  }
  return { view: NotFound, params: {} };
}

export default function App() {
  const theme = useTheme();
  const [auth, setAuth] = useState<"checking" | "ok" | "needed">("checking");
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [down, setDown] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [confirm, confirmDialog] = useConfirm();
  const [drawer, setDrawer] = useState(false);
  const wide = useWide();
  const path = useRoute();
  const { at, canBack, canForward, returned } = useHistoryPlace();
  const { main, onScroll } = useScrollMemory(at, returned);

  useEffect(() => {
    api.auth().then((a) => setAuth(a.ok ? "ok" : "needed"), () => setAuth("ok"));
    const onAuth = () => setAuth("needed");
    window.addEventListener(AUTH_EVENT, onAuth);
    return () => window.removeEventListener(AUTH_EVENT, onAuth);
  }, []);

  // The app info doubles as the "is the server up?" check; retry quietly until it answers.
  useEffect(() => {
    if (auth !== "ok") return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = () =>
      api.app().then(
        (a) => {
          if (!alive) return;
          setSystem(a.computer);
          setInfo(a);
          setDown(false);
          document.title = a.name;
          startChangeFeed();
        },
        () => {
          if (!alive) return;
          setDown(true);
          timer = setTimeout(load, 3000);
        },
      );
    void load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [auth]);

  // What's on can change while the app is open (a connection gets set up), so the app info is read again whenever
  // anything changes on the server. Only the latest answer counts, and none from before a change made here.
  const changes = useChanges();
  const asked = useRef(0);
  const setInfoHere = useCallback((change: (i: AppInfo) => AppInfo) => {
    asked.current += 1;
    setInfo((i) => (i ? change(i) : i));
  }, []);
  useEffect(() => {
    if (!changes) return;
    const mine = ++asked.current;
    api.app().then((a) => mine === asked.current && setInfo(a), () => undefined);
  }, [changes]);

  // Pages, the sidebar and the Mac menu show the modules that are on; Settings lists every one (a connection that
  // isn't set up yet is how you set it up).
  const modules = useMemo(() => modulesFor(info?.modules.filter((m) => m.active).map((m) => m.id) ?? []), [info]);

  // The Mac app's menu bar menu lists the same sections as the sidebar (it keeps them for when no window is open).
  useEffect(() => {
    if (info) showInAppMenu(modules.flatMap((m) => (m.nav ?? []).map(({ label, path }) => ({ label, path }))));
  }, [info, modules]);

  // A single-module app with nothing for Home opens straight into that module.
  useEffect(() => {
    if (path === "" && modules.length === 1 && !modules[0].home && modules[0].nav?.[0]) navigate(modules[0].nav[0].path);
  }, [path, modules]);

  useStartPage(modules);

  useEffect(() => setDrawer(false), [path]);

  const toastFn = useCallback((text: string, tone: "success" | "error" = "success") => setToast({ text, tone }), []);
  const reopenSetup = useCallback(async () => {
    await api.setupReopen();
    setInfoHere((i) => ({ ...i, setup_done: false }));
  }, [setInfoHere]);
  const shell: Shell | null = useMemo(() => (info ? { app: info, toast: toastFn, confirm, theme, reopenSetup } : null), [info, toastFn, confirm, theme, reopenSetup]);

  if (auth === "needed") return <Login onDone={() => setAuth("ok")} dusk={theme.dusk} />;
  if (!shell) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-5 text-center">
        <Ambient />
        <div className="relative animate-soft-pulse">
          <Logo size={44} />
        </div>
        {down && <p className="relative text-ui text-ink-soft">Waiting for the server to start…</p>}
      </div>
    );
  }

  if (!info!.setup_done) {
    return (
      <ShellProvider value={shell}>
        <Welcome dusk={theme.dusk} onDone={() => setInfoHere((i) => ({ ...i, setup_done: true }))} />
        <TooltipLayer />
        <Toast toast={toast} onClose={() => setToast(null)} />
      </ShellProvider>
    );
  }

  const { view: View, params, wide: fullWidth } = resolve(path, modules);

  return (
    <ShellProvider value={shell}>
      <div className="relative flex h-full">
        <Ambient />
        <div
          className={`fixed inset-y-0 left-0 z-40 transition-[transform,visibility] duration-300 ease-out lg:static lg:z-10 lg:translate-x-0 ${
            drawer || wide ? "visible translate-x-0" : "invisible -translate-x-full"
          }`}
        >
          <Sidebar modules={modules} path={path} opaque={!wide} />
        </div>
        {drawer && !wide && <div className="fixed inset-0 z-30 animate-fade-in bg-[var(--scrim)] backdrop-blur-[2px]" onClick={() => setDrawer(false)} />}

        <main ref={main} onScroll={onScroll} className="relative z-10 min-w-0 flex-1 overflow-y-auto">
          <div className="chrome sticky top-0 z-20 flex h-14 items-center gap-2 border-b border-line px-3 lg:h-11">
            <button className="icon-btn h-10 w-10 lg:hidden" aria-label="Open the sidebar" onClick={() => setDrawer(true)}>
              <MenuIcon size={20} />
            </button>
            <BackForward canBack={canBack} canForward={canForward} />
            <span className="contents lg:hidden">
              <Logo size={26} />
              <span className="min-w-0 truncate font-display text-lead font-semibold tracking-[-0.02em]">{info!.name}</span>
              <LockdownSign compact />
            </span>
          </div>
          <div key={path} className={`relative mx-auto w-full px-5 pb-24 pt-7 sm:px-8 lg:pt-9 ${fullWidth ? "max-w-[1400px] lg:px-8" : "max-w-[872px] lg:px-10"}`}>
            <View params={params} />
          </div>
        </main>
      </div>
      {modules.map((m) => {
        const Background = m.background;
        return Background ? <Background key={m.id} /> : null;
      })}
      <TooltipLayer />
      <Toast toast={toast} onClose={() => setToast(null)} />
      {confirmDialog}
    </ShellProvider>
  );
}
