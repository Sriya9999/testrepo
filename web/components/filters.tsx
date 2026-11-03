"use client";

import { useState } from "react";
import { cn } from "./ui";

export interface DateRange { start: string; end: string; days: number }

function iso(d: Date) {
  return d.toISOString().slice(0, 10);
}

export function rangeFor(days: number): DateRange {
  const end = new Date();
  const start = new Date(end.getTime() - (days - 1) * 86_400_000);
  return { start: iso(start), end: iso(end), days };
}

export function useDateRange(initial = 30) {
  return useState<DateRange>(() => rangeFor(initial));
}

/** Date-range control; the comparison period is always the same length immediately before. */
export function RangePicker({ value, onChange }: { value: DateRange; onChange: (r: DateRange) => void }) {
  return (
    <div className="inline-flex rounded-[var(--radius-control)] border border-rule-strong bg-surface p-0.5" role="group" aria-label="Date range">
      {[7, 30, 90].map((d) => (
        <button key={d} onClick={() => onChange(rangeFor(d))} aria-pressed={value.days === d}
          className={cn("rounded px-2.5 py-1 text-[13px]", value.days === d ? "bg-ink text-white" : "text-ink-2 hover:bg-sunk")}>
          {d} days
        </button>
      ))}
    </div>
  );
}
