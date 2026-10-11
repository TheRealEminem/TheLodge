import { useEffect, useRef, useState } from "react";
import { formatDate } from "./format";

interface Point {
  week: string;
  meetings: number;
}

function niceMax(v: number): number {
  if (v <= 4) return 4;
  const step = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 4, 6, 8, 10]) if (m * step >= v) return m * step; // even, so the midline tick is whole
  return 10 * step;
}

/** Meetings per week: one series, so no legend (the section title names it). Has a table view. */
export default function ActivityChart({ data, height = 170 }: { data: Point[]; height?: number }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const pad = { top: 10, right: 4, bottom: 22, left: 26 };
  const innerW = Math.max(width - pad.left - pad.right, 50);
  const innerH = height - pad.top - pad.bottom;
  const max = niceMax(Math.max(...data.map((d) => d.meetings), 1));
  const ticks = [0, max / 2, max];
  const slot = innerW / Math.max(data.length, 1);
  const barW = Math.min(Math.max(slot - 4, 3), 24);
  const y = (v: number) => pad.top + innerH - (v / max) * innerH;
  const total = data.reduce((s, d) => s + d.meetings, 0);
  const monthStarts = data
    .map((d, i) => ({ i, date: new Date(`${d.week}T12:00:00`) }))
    .filter(({ i, date }) => i > 0 && date.getMonth() !== new Date(`${data[i - 1].week}T12:00:00`).getMonth());

  return (
    <div ref={wrap} className="relative">
      <div className="mb-1 flex items-baseline justify-between">
        <p className="text-hint text-ink-soft">
          <span className="font-semibold text-ink">{total}</span> meetings in the last {data.length} weeks
        </p>
        <button className="btn btn-sm btn-ghost" onClick={() => setAsTable((t) => !t)}>
          {asTable ? "Show chart" : "Show table"}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-[170px] overflow-y-auto">
          <table className="w-full text-ui tabular-nums">
            <thead className="text-left text-ink-soft">
              <tr>
                <th className="py-1 font-medium">Week of</th>
                <th className="py-1 text-right font-medium">Meetings</th>
              </tr>
            </thead>
            <tbody>
              {[...data].reverse().map((d) => (
                <tr key={d.week} className="border-t border-line">
                  <td className="py-1 text-ink-soft">{formatDate(d.week)}</td>
                  <td className="py-1 text-right">{d.meetings}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <svg width={width} height={height} role="img" aria-label={`Bar chart of meetings per week, ${total} in total`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--border-strong)" : "var(--border)"} strokeWidth={1} />
              <text x={pad.left - 6} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--text-secondary)">
                {t}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const cx = pad.left + slot * i + slot / 2;
            const top = y(d.meetings);
            const h = Math.max(pad.top + innerH - top, 0);
            const r = Math.min(4, h, barW / 2);
            return (
              <g key={d.week}>
                {h > 0 && (
                  <path
                    d={`M${cx - barW / 2},${top + h} V${top + r} Q${cx - barW / 2},${top} ${cx - barW / 2 + r},${top} H${cx + barW / 2 - r} Q${cx + barW / 2},${top} ${cx + barW / 2},${top + r} V${top + h} Z`}
                    fill="var(--forest)"
                    opacity={hover === null || hover === i ? 1 : 0.55}
                  />
                )}
                <rect
                  x={pad.left + slot * i}
                  y={pad.top}
                  width={slot}
                  height={innerH}
                  fill="transparent"
                  tabIndex={0}
                  aria-label={`Week of ${formatDate(d.week)}: ${d.meetings} meetings`}
                  onPointerEnter={() => setHover(i)}
                  onPointerLeave={() => setHover(null)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                />
              </g>
            );
          })}
          {monthStarts.map(({ i, date }) => (
            <text key={i} x={pad.left + slot * i + slot / 2} y={height - 6} fontSize={11} fill="var(--text-secondary)" textAnchor="start">
              {date.toLocaleDateString(undefined, { month: "short" })}
            </text>
          ))}
        </svg>
      )}
      {!asTable && hover !== null && (
        <div
          className="panel pointer-events-none absolute z-10 px-2.5 py-1.5 shadow-lg"
          style={{ left: Math.min(pad.left + slot * hover + slot / 2 + 8, width - 150), top: Math.max(y(data[hover].meetings) - 10, 20) }}
        >
          <div className="text-ui font-semibold tabular-nums">{data[hover].meetings} meetings</div>
          <div className="text-meta text-ink-soft">Week of {formatDate(data[hover].week)}</div>
        </div>
      )}
    </div>
  );
}
