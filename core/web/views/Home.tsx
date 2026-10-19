// Home: the place where every module shows what's new. In the unified app this is the front door.
import type { CSSProperties } from "react";
import { Scene } from "../components/illustrations";
import { useShell } from "../shell";
import { modulesFor } from "../registry";

const greeting = () => {
  const h = new Date().getHours();
  return h < 5 ? "Good evening" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
};

export default function Home() {
  const { app, theme } = useShell();
  const cards = modulesFor(app.modules.map((m) => m.id)).filter((m) => m.home);
  return (
    <div className="flex flex-col">
      <div className="relative animate-enter">
        <div aria-hidden="true" className="absolute inset-x-[10%] bottom-0 top-1/3 rounded-hero bg-forest/10 blur-3xl" />
        <div className="art-frame h-[clamp(150px,18vw+40px,220px)]">
          <Scene parallax dusk={theme.dusk} className="absolute inset-0 h-full w-full" />
        </div>
      </div>
      <div className="mt-8 animate-enter" style={{ animationDelay: "60ms" } as CSSProperties}>
        <p className="eyebrow mb-2.5">{new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</p>
        <h1 className="hero-title">{greeting()}</h1>
        {app.tagline && <p className="hero-sub mt-3">{app.name}: {app.tagline}.</p>}
      </div>
      <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {cards.map((m, i) => {
          const Card = m.home!;
          const delay = { animationDelay: `${120 + i * 60}ms` } as CSSProperties;
          return m.homeWide ? (
            <div key={m.id} className="animate-enter sm:col-span-2" style={delay}>
              <Card />
            </div>
          ) : (
            <section key={m.id} className="panel animate-enter p-5" style={delay}>
              <Card />
            </section>
          );
        })}
      </div>
    </div>
  );
}
