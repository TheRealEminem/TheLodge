import { KIND_LABEL } from "./bits";
import { KIND_SHAPE, ShapeGlyph } from "./graphShapes";

export function GraphLegend({ kinds }: { kinds?: string[] }) {
  const shown = (["person", "organization", "meeting", "document", "topic"] as const).filter((k) => !kinds || kinds.includes(k));
  return (
    <div className="space-y-1 text-meta text-ink-soft">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {shown.map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <ShapeKey kind={k} /> {KIND_LABEL[k].many}
          </span>
        ))}
      </div>
      {shown.includes("person") && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>People:</span>
          <span className="inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full bg-forest" /> strong</span>
          <span className="inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full bg-forest/55" /> working</span>
          <span className="inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full border-[1.6px] border-forest" /> light</span>
          <span className="inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full border-[1.6px] border-dotted border-ink-soft" /> indirect or not linked</span>
        </div>
      )}
    </div>
  );
}

const ShapeKey = ({ kind }: { kind: keyof typeof KIND_SHAPE }) => <ShapeGlyph shape={KIND_SHAPE[kind]} className="text-ink-soft" />;
