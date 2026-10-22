import { GROUP_META, GROUP_ORDER, GroupGlyph } from "./groups";

/** What the network's marks mean: how well you know someone (fill), what a line says, and what a group's outline is. */
export function GraphLegend({ wells, preset = false, events }: { wells: boolean; preset?: boolean; events: boolean }) {
  return (
    <div className="space-y-1 text-meta text-ink-soft">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span>People:</span>
        <span className="inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full bg-forest" /> strong</span>
        <span className="inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full bg-forest/55" /> working</span>
        <span className="inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full border-[1.6px] border-forest" /> light</span>
        <span className="inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full border-[1.6px] border-dotted border-ink-soft" /> indirect or not linked</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span>Lines:</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-0 w-5 border-t-2 border-line-strong" /> you recorded it</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-0 w-5 border-t border-line-strong" /> were at the same meeting</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-0 w-5 border-t border-dotted border-ink-soft" /> came up there</span>
        {events && <span>Click a person to see their meetings and documents.</span>}
      </div>
      {(wells || preset) && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>Groups:</span>
          {[...GROUP_ORDER, ...(preset ? ["preset" as const] : [])].map((k) => (
            <span key={k} className="inline-flex items-center gap-1.5"><GroupGlyph kind={k} className="text-forest" /> {GROUP_META[k].one.toLowerCase()}</span>
          ))}
        </div>
      )}
    </div>
  );
}
