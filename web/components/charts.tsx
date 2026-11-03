"use client";

import { useId, useMemo, useState } from "react";

/* Validated categorical order (light surface): series-1 blue, series-2 leaf, series-3 amber.
   Colour follows the series key, never its rank. */
export const SERIES_COLORS = ["var(--color-series-1)", "var(--color-series-2)", "var(--color-series-3)"];

export interface Series {
  key: string;
  label: string;
  color: string;
  values: (number | null)[];
}

interface LineChartProps {
  labels: string[];
  series: Series[];
  height?: number;
  format?: (v: number) => string;
  title: string;
}

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return Math.ceil(v / p) * p;
}

function shortDate(iso: string) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

/** Multi-series line chart with a crosshair tooltip. One y-axis only. */
export function LineChart({ labels, series, height = 200, format = (v) => v.toLocaleString("en-IN"), title }: LineChartProps) {
  const id = useId();
  const [hover, setHover] = useState<number | null>(null);
  const width = 640;
  const pad = { top: 12, right: 28, bottom: 26, left: 52 };
  const values = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  const max = niceMax(Math.max(0, ...values));
  const n = labels.length;
  const x = (i: number) => pad.left + (n <= 1 ? 0 : (i * (width - pad.left - pad.right)) / (n - 1));
  const y = (v: number) => pad.top + (1 - v / max) * (height - pad.top - pad.bottom);
  const ticks = [0, max / 2, max];
  const tickEvery = Math.max(1, Math.ceil(n / 6));

  const paths = useMemo(
    () =>
      series.map((s) => {
        let d = "";
        s.values.forEach((v, i) => {
          if (v === null) return;
          d += `${d && s.values[i - 1] !== null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        });
        return d;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [series, max, n],
  );

  if (!values.length) {
    return <p className="py-10 text-center text-[13px] text-muted">No data in this period yet.</p>;
  }

  return (
    <figure className="relative" aria-labelledby={`${id}-t`}>
      <figcaption id={`${id}-t`} className="sr-only">{title}</figcaption>
      {series.length > 1 && (
        <div className="mb-2 flex flex-wrap gap-4 text-xs text-ink-2">
          {series.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5">
              <span className="inline-block h-0.5 w-4 rounded" style={{ background: s.color }} /> {s.label}
            </span>
          ))}
        </div>
      )}
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label={title}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = ((e.clientX - rect.left) / rect.width) * width;
          const i = Math.round(((px - pad.left) / (width - pad.left - pad.right)) * (n - 1));
          setHover(Math.max(0, Math.min(n - 1, i)));
        }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} stroke="var(--color-rule)" strokeDasharray={t === 0 ? undefined : "2 4"} />
            <text x={pad.left - 8} y={y(t) + 4} textAnchor="end" fontSize="12" fill="var(--color-muted)">{format(t)}</text>
          </g>
        ))}
        {labels.map((l, i) =>
          i % tickEvery === 0 ? (
            <text key={l} x={x(i)} y={height - 6} textAnchor="middle" fontSize="12" fill="var(--color-muted)">{shortDate(l)}</text>
          ) : null,
        )}
        {paths.map((d, i) => (
          <path key={series[i].key} d={d} fill="none" stroke={series[i].color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={pad.top} y2={height - pad.bottom} stroke="var(--color-rule-strong)" />
            {series.map((s) =>
              s.values[hover] !== null ? (
                <circle key={s.key} cx={x(hover)} cy={y(s.values[hover] as number)} r="4" fill={s.color} stroke="white" strokeWidth="2" />
              ) : null,
            )}
          </g>
        )}
      </svg>
      {hover !== null && (
        <div
          className="pointer-events-none absolute top-6 z-10 min-w-36 rounded-md border border-rule bg-surface px-3 py-2 text-xs shadow-lg"
          style={{ left: `${(x(hover) / width) * 100}%`, transform: x(hover) > width * 0.6 ? "translateX(calc(-100% - 12px))" : "translateX(12px)" }}
        >
          <p className="mb-1 font-medium">{shortDate(labels[hover])}</p>
          {series.map((s) => (
            <p key={s.key} className="flex items-center justify-between gap-3 tabular">
              <span className="inline-flex items-center gap-1.5 text-ink-2"><span className="size-2 rounded-full" style={{ background: s.color }} />{s.label}</span>
              <span className="font-medium">{s.values[hover] === null ? "—" : format(s.values[hover] as number)}</span>
            </p>
          ))}
        </div>
      )}
    </figure>
  );
}

/** Horizontal bars for comparing a handful of named values. */
export function BarList({ items, format = (v) => v.toLocaleString("en-IN"), color = SERIES_COLORS[0] }: { items: { label: string; value: number; note?: string }[]; format?: (v: number) => string; color?: string }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  if (!items.length) return <p className="py-6 text-center text-[13px] text-muted">Nothing to compare yet.</p>;
  return (
    <ul className="space-y-2.5">
      {items.map((i) => (
        <li key={i.label} title={`${i.label}: ${format(i.value)}`}>
          <div className="mb-1 flex justify-between gap-3 text-[13px]">
            <span className="truncate">{i.label}</span>
            <span className="tabular font-medium">{format(i.value)}</span>
          </div>
          <div className="h-2 rounded-full bg-sunk">
            <div className="h-2 rounded-full" style={{ width: `${Math.max(2, (i.value / max) * 100)}%`, background: color }} />
          </div>
          {i.note && <p className="mt-0.5 text-xs text-muted">{i.note}</p>}
        </li>
      ))}
    </ul>
  );
}

/** Score ring for 0–100 internal indicators (SEO health, GEO visibility). */
export function ScoreRing({ value, label, size = 96 }: { value: number | null; label: string; size?: number }) {
  const r = size / 2 - 7;
  const c = 2 * Math.PI * r;
  const v = value ?? 0;
  const color = value === null ? "var(--color-rule)" : v >= 75 ? "var(--color-leaf)" : v >= 50 ? "var(--color-series-3)" : "var(--color-danger)";
  return (
    <div className="flex flex-col items-center gap-1" role="img" aria-label={`${label}: ${value ?? "not measured"}`}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-sunk)" strokeWidth="7" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="7" strokeLinecap="round"
          strokeDasharray={`${(v / 100) * c} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
        <text x="50%" y="52%" dominantBaseline="middle" textAnchor="middle" fontSize={size / 3.6} fontWeight="700" fill="var(--color-ink)">
          {value ?? "—"}
        </text>
      </svg>
      <span className="text-xs text-muted">{label}</span>
    </div>
  );
}
