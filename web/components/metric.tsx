"use client";

import { formatKpi, type Kpi } from "@marketingos/api-client";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { cn, ProvenanceMark } from "./ui";

export function Metric({ label, kpi, currency, href }: { label: string; kpi: Kpi | undefined; currency: string; href?: string }) {
  if (!kpi) return null;
  const change = kpi.change_pct;
  const good = change === null ? null : kpi.lower_is_better ? change < 0 : change > 0;
  const body = (
    <div className="flex h-full flex-col justify-between gap-2 px-4 py-3.5">
      <div className="flex items-center gap-1.5 text-[13px] text-muted">
        <ProvenanceMark kind={kpi.kind} />
        {label}
      </div>
      <div className="flex items-baseline justify-between gap-2">
        <span className={cn("tabular text-[22px] font-bold tracking-tight", kpi.value === null && "text-faint")}>{formatKpi(kpi, currency)}</span>
        {change !== null && (
          <span className={cn("inline-flex items-center gap-0.5 text-xs font-medium tabular", good ? "text-leaf" : "text-danger")}>
            {change >= 0 ? <ArrowUpRight className="size-3" aria-hidden /> : <ArrowDownRight className="size-3" aria-hidden />}
            {Math.abs(change).toFixed(1)}%
            <span className="sr-only">{good ? "(improved)" : "(worse)"} vs previous period</span>
          </span>
        )}
      </div>
    </div>
  );
  return href ? (
    <a href={href} className="block h-full hover:bg-paper">{body}</a>
  ) : (
    body
  );
}

export function MetricGrid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 divide-rule overflow-hidden rounded-[var(--radius-panel)] border border-rule bg-surface sm:grid-cols-3 lg:grid-cols-6 [&>*]:border-b [&>*]:border-r [&>*]:border-rule">
      {children}
    </div>
  );
}

export function ProvenanceLegend() {
  return (
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      <span className="inline-flex items-center gap-1"><ProvenanceMark kind="measured" /> measured by the platform</span>
      <span className="inline-flex items-center gap-1"><ProvenanceMark kind="calculated" /> calculated</span>
      <span className="inline-flex items-center gap-1"><ProvenanceMark kind="internal" /> MarketingOS indicator</span>
    </p>
  );
}
