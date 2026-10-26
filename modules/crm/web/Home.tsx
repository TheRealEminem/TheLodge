// The People block on Home: who you know, how well, and who your recent meetings brought into view.
import { useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { CalendarIcon, ClockIcon, CompassIcon, MergeIcon, OrgIcon, PlusIcon, SearchIcon, SparkleIcon, UsersIcon } from "@core/components/icons";
import { Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { useShell } from "@core/shell";
import ActivityChart from "./ActivityChart";
import { crmApi } from "./api";
import type { PersonRow, Tier } from "./api";
import { Avatar, Empty, roleLine } from "./bits";
import { formatDate, relativeTime } from "./format";
import { OrgLine } from "./Organizations";
import { GeminiDialog } from "./GeminiResearch";
import PersonFinder from "./PersonFinder";
import { TIER_META, TierBars, connectionLine } from "./tier";

/** "Research these with Gemini" under the Needs research list. */
function ResearchThese({ rows }: { rows: PersonRow[] }) {
  const [open, setOpen] = useState(false);
  const people = rows.filter((r) => r.person.name.trim().includes(" ")).map((r) => ({ id: r.person.id, name: r.person.name }));
  if (!people.length) return null;
  return (
    <div className="mt-3 px-1">
      <button className="btn btn-sm btn-soft" onClick={() => setOpen(true)}><SparkleIcon size={16} /> Research {people.length === 1 ? "them" : `these ${people.length}`} with Gemini</button>
      {open && <GeminiDialog people={people} onClose={() => setOpen(false)} />}
    </div>
  );
}

function HomeSection({ icon, title, blurb, href, more, delay = 0, children }: {
  icon: ReactNode;
  title: string;
  blurb?: string;
  href?: string;
  more?: string;
  delay?: number;
  children: ReactNode;
}) {
  return (
    <section className="mb-10 animate-enter" style={{ animationDelay: `${delay}ms` } as CSSProperties}>
      <div className="mb-3 flex items-start gap-3 px-1">
        <span className="well well-forest">{icon}</span>
        <div className="min-w-0 flex-1">
          <h2 className="text-heading font-semibold tracking-[-0.01em]">{title}</h2>
          {blurb && <p className="mt-0.5 text-ui leading-snug text-ink-soft">{blurb}</p>}
        </div>
        {href && more && (
          <a href={href} className="mt-1 shrink-0 text-ui font-medium text-forest-deep hover:underline">
            {more}
          </a>
        )}
      </div>
      {children}
    </section>
  );
}

function PersonRows({ rows, empty, detail }: { rows: PersonRow[]; empty: string; detail?: (r: PersonRow) => string }) {
  if (!rows.length) return <p className="inset-surface px-5 py-4 text-ui text-ink-soft">{empty}</p>;
  return (
    <div className="panel divide-y divide-line overflow-hidden">
      {rows.map((r) => (
        <a key={r.person.id} href={`#/crm/e/${r.person.id}`} className="flex items-center gap-3.5 px-5 py-3 transition-colors duration-150 hover:bg-forest/[.05]">
          <Avatar id={r.person.id} name={r.person.name} />
          <div className="min-w-0 flex-1">
            <div className="truncate text-label font-medium">{r.person.name}</div>
            <div className="truncate text-hint text-ink-soft">{roleLine(r.title, r.org?.name) || "\u00a0"}</div>
          </div>
          <div className="max-w-[45%] shrink-0 truncate text-right text-meta text-ink-soft">{(detail ?? ((x) => connectionLine(x.connection)))(r)}</div>
        </a>
      ))}
    </div>
  );
}

function TierTile({ tier, count }: { tier: Tier; count: number }) {
  return (
    <a href={`#/crm/people?tier=${tier}`} className="panel block min-w-0 px-4 py-3.5 transition-[transform,box-shadow] duration-150 hover:-translate-y-px hover:shadow-md">
      <div className="flex items-center gap-1.5 text-ui text-ink-soft">
        <TierBars tier={tier} /> {TIER_META[tier].label}
      </div>
      <div className="mt-1.5 page-title leading-none tabular-nums">{count.toLocaleString()}</div>
      <div className="mt-2 truncate text-meta text-ink-soft">{TIER_META[tier].blurb}</div>
    </a>
  );
}

function Onboarding() {
  const { toast } = useShell();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="panel p-5">
      <h2 className="text-heading font-semibold tracking-[-0.01em]">Start with you</h2>
      <p className="mt-1 text-ui text-ink-soft">Connections are measured from you, so tell The Lodge who you are.</p>
      <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) void run(() => crmApi.setMe(name.trim())); }}>
        <input className="field h-10 flex-1" placeholder="Your name" aria-label="Your name" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn btn-md btn-primary" disabled={!name.trim() || busy}>
          <PlusIcon size={18} /> Continue
        </button>
      </form>
      <p className="mt-4 text-hint text-ink-soft">Just looking around? <button className="font-medium text-forest-deep hover:underline" disabled={busy} onClick={() => void run(crmApi.loadDemo)}>Load a fictional network</button>.</p>
    </div>
  );
}

export default function HomeBlock() {
  const { data } = useLive(crmApi.dashboard);
  if (!data) return <Skeleton className="h-64 w-full rounded-xl" />;
  const total = Object.values(data.counts).reduce((a, b) => a + (b ?? 0), 0);
  if (total === 0 || (total === 1 && data.me)) return <Onboarding />;

  const tiers: Tier[] = ["strong", "working", "light", "indirect"];
  return (
    <>
      <PersonFinder />
      <div className="mb-10 grid animate-enter grid-cols-2 gap-3 lg:grid-cols-4">
        {tiers.map((t) => (
          <TierTile key={t} tier={t} count={data.tiers[t] ?? 0} />
        ))}
      </div>

      <HomeSection icon={<UsersIcon size={16} />} title="Strong connections" blurb="The people closest to you." href="#/crm/people?tier=strong" more={`All ${data.tiers.strong ?? 0}`} delay={60}>
        <PersonRows rows={data.strong} empty="Rate someone 4 or 5 on their profile to mark them as a strong connection." />
      </HomeSection>

      <HomeSection icon={<UsersIcon size={16} />} title="Working relationships" blurb="Colleagues, advisors and people you meet regularly." href="#/crm/people?tier=working" more={`All ${data.tiers.working ?? 0}`} delay={90}>
        <PersonRows rows={data.working} empty="Colleagues and advisors show up here." />
      </HomeSection>

      <HomeSection icon={<SparkleIcon size={16} />} title="Lit up by your meetings" blurb="Light and indirect connections, newest first." delay={120}>
        <PersonRows
          rows={data.lit_up}
          empty="People who come up in your meetings appear here."
          detail={(r) =>
            r.connection.via.length
              ? `via ${r.connection.via.slice(0, 2).map((v) => v.name).join(", ")}`
              : r.connection.last_met_at
                ? `met ${relativeTime(r.connection.last_met_at)}`
                : connectionLine(r.connection)
          }
        />
      </HomeSection>

      <HomeSection icon={<ClockIcon size={16} />} title="Reconnect" blurb="Strong and working connections you haven't met in 60 days or more." delay={150}>
        <PersonRows rows={data.reconnect} empty="No one close has gone quiet." detail={(r) => `last met ${relativeTime(r.connection.last_met_at)}`} />
      </HomeSection>

      {data.research_needed > 0 && (
        <HomeSection
          icon={<SearchIcon size={16} />}
          title="Needs research"
          blurb={data.research_close > 0
            ? `${data.research_close} ${data.research_close === 1 ? "person" : "people"} you know well ${data.research_close === 1 ? "has" : "have"} no background on file. The ones who matter most are first.`
            : "People with no background on file. The ones who matter most are first."}
          href="#/crm/people?research=needed"
          more={`All ${data.research_needed}`}
          delay={165}
        >
          <PersonRows rows={data.research} empty="" detail={(r) => connectionLine(r.connection) || "no background yet"} />
          <ResearchThese rows={data.research} />
        </HomeSection>
      )}

      {data.duplicates > 0 && (
        <HomeSection icon={<MergeIcon size={16} />} title="Possible duplicates" delay={170}
          blurb={`${data.duplicates} ${data.duplicates === 1 ? "pair of records looks" : "pairs of records look"} like the same person or organization twice. Nothing is merged until you say so.`}>
          <a href="#/crm/duplicates" className="btn btn-sm btn-soft"><MergeIcon size={16} /> Review {data.duplicates === 1 ? "it" : "them"}</a>
        </HomeSection>
      )}

      <HomeSection icon={<OrgIcon size={16} />} title="Where you know people" href="#/crm/organizations" more="All organizations" delay={180}>
        {data.key_orgs.length === 0 ? (
          <Empty icon={<CompassIcon size={20} />} title="No organizations yet">Organizations appear once you know someone there.</Empty>
        ) : (
          <div className="panel divide-y divide-line overflow-hidden">
            {data.key_orgs.map((o) => (
              <OrgLine key={o.org.id} row={o} />
            ))}
          </div>
        )}
      </HomeSection>

      <HomeSection icon={<CalendarIcon size={16} />} title="Recent meetings" href="#/crm/meetings" more="All meetings" delay={210}>
        {data.recent_meetings.length === 0 ? (
          <p className="inset-surface px-5 py-4 text-ui text-ink-soft">No meetings yet.</p>
        ) : (
          <div className="panel divide-y divide-line overflow-hidden">
            {data.recent_meetings.map(({ meeting, attendees, discussed }) => (
              <a key={meeting.id} href={`#/crm/e/${meeting.id}`} className="flex items-center gap-3.5 px-5 py-3 transition-colors duration-150 hover:bg-forest/[.05]">
                <span className="well"><CalendarIcon size={16} /></span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-label font-medium">{meeting.name}</div>
                  <div className="truncate text-hint text-ink-soft">
                    {attendees.length ? `with ${attendees.map((a) => a.name).join(", ")}` : "No attendees recorded"}
                    {discussed.length > 0 && ` · ${discussed.length} ${discussed.length === 1 ? "person" : "people"} came up`}
                  </div>
                </div>
                <span className="shrink-0 text-meta text-ink-soft">{formatDate(meeting.occurred_at, { year: undefined })}</span>
              </a>
            ))}
          </div>
        )}
      </HomeSection>

      <HomeSection icon={<CalendarIcon size={16} />} title="Meetings per week" delay={240}>
        <div className="panel p-5">
          <ActivityChart data={data.weekly_activity} />
        </div>
      </HomeSection>
    </>
  );
}
