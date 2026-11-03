"use client";

import { STATUS_LABELS } from "@marketingos/api-client";
import { AlertTriangle, CheckCircle2, Circle, CircleDot, Clock, Loader2, X, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

export function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "approve" | "danger" | "signoff";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-ink text-white hover:bg-ink-2 border border-ink",
  secondary: "bg-surface text-ink border border-rule-strong hover:bg-sunk",
  ghost: "text-ink-2 hover:bg-sunk border border-transparent",
  approve: "bg-leaf text-white border border-leaf hover:brightness-110",
  danger: "bg-surface text-danger border border-rule-strong hover:bg-danger-wash",
  signoff: "bg-marigold text-ink border border-marigold-deep/30 hover:brightness-105 font-semibold",
};

export function Button({
  variant = "secondary", size = "md", loading, className, children, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-control)] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 whitespace-nowrap",
        size === "sm" ? "h-8 px-2.5 text-[13px]" : "h-9 px-3.5 text-sm",
        VARIANTS[variant],
        className,
      )}
    >
      {loading && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function LinkButton({ href, children, variant = "secondary", className }: { href: string; children: ReactNode; variant?: Variant; className?: string }) {
  return (
    <Link href={href} className={cn("inline-flex h-9 items-center justify-center gap-1.5 rounded-[var(--radius-control)] px-3.5 text-sm font-medium", VARIANTS[variant], className)}>
      {children}
    </Link>
  );
}

const control = "rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3 text-sm text-ink placeholder:text-faint focus:border-series-1 focus:outline-none";

const width = (className?: string) => (className && /(^|\s)w-/.test(className) ? "" : "w-full");

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn(control, width(props.className), "h-9", props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(control, width(props.className), "py-2 leading-relaxed", props.className)} />;
}

export function Select({ options, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { options: { value: string; label: string }[] }) {
  return (
    <select {...props} className={cn(control, width(props.className), "h-9 pr-8", props.className)}>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

export function Field({ label, hint, error, children, className }: { label: string; hint?: ReactNode; error?: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block space-y-1.5", className)}>
      <span className="block text-[13px] font-medium text-ink-2">{label}</span>
      {children}
      {hint && !error && <span className="block text-xs text-muted">{hint}</span>}
      {error && <span className="block text-xs text-danger">{error}</span>}
    </label>
  );
}

export function Panel({ children, className, title, actions, description }: { children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode; description?: ReactNode }) {
  return (
    <section className={cn("min-w-0 rounded-[var(--radius-panel)] border border-rule bg-surface", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-rule px-5 py-3.5">
          <div>
            {title && <h2 className="text-[15px] font-semibold">{title}</h2>}
            {description && <p className="mt-0.5 text-[13px] text-muted">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn(title || actions ? "p-5" : "")}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="text-[26px] font-bold leading-tight tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-[15px] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const STATUS_STYLE: Record<string, { cls: string; icon: typeof Circle }> = {
  good: { cls: "bg-leaf-wash text-leaf", icon: CheckCircle2 },
  wait: { cls: "bg-marigold-wash text-marigold-deep", icon: Clock },
  bad: { cls: "bg-danger-wash text-danger", icon: XCircle },
  neutral: { cls: "bg-sunk text-ink-2", icon: Circle },
  busy: { cls: "bg-sunk text-ink-2", icon: Loader2 },
};

const STATUS_GROUP: Record<string, keyof typeof STATUS_STYLE> = {
  approved: "good", published: "good", executed: "good", active: "good", completed: "good", connected: "good", ready: "good", succeeded: "good", paid: "good",
  pending: "wait", in_review: "wait", pending_approval: "wait", awaiting_approval: "wait", scheduled: "wait", changes_requested: "wait", trialing: "wait", needs_integration: "wait",
  failed: "bad", rejected: "bad", error: "bad", past_due: "bad",
  publishing: "busy", submitting: "busy", running: "busy", queued: "busy",
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const style = STATUS_STYLE[STATUS_GROUP[status] ?? "neutral"];
  const Icon = style.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", style.cls)}>
      <Icon className={cn("size-3", style.icon === Loader2 && "animate-spin")} aria-hidden />
      {label ?? STATUS_LABELS[status] ?? status.replace(/_/g, " ")}
    </span>
  );
}

export function Tag({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "sandbox" | "ai" }) {
  const cls = { neutral: "bg-sunk text-ink-2", sandbox: "bg-[#e8eef8] text-series-1", ai: "border border-dashed border-rule-strong text-ink-2" }[tone];
  return <span className={cn("inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium", cls)}>{children}</span>;
}

/** Where a number comes from: measured by a platform, calculated from measured values, or a MarketingOS indicator. */
export function ProvenanceMark({ kind }: { kind: string }) {
  const map: Record<string, { icon: typeof Circle; label: string }> = {
    measured: { icon: CircleDot, label: "Measured: reported by the platform" },
    calculated: { icon: Circle, label: "Calculated from measured values" },
    internal: { icon: Circle, label: "MarketingOS indicator, not a platform metric" },
    estimate: { icon: Circle, label: "Statistical estimate" },
  };
  const m = map[kind] ?? map.calculated;
  const Icon = m.icon;
  return (
    <span title={m.label} aria-label={m.label} className="inline-flex text-faint">
      <Icon className={cn("size-3", kind === "internal" && "opacity-60", kind === "calculated" && "[stroke-dasharray:3_2]")} />
    </span>
  );
}

export function Empty({ title, body, action }: { title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-[var(--radius-panel)] border border-dashed border-rule-strong px-6 py-10 text-center">
      <p className="font-semibold">{title}</p>
      {body && <p className="mx-auto mt-1 max-w-md text-[13px] text-muted">{body}</p>}
      {action && <div className="mt-4 flex justify-center gap-2">{action}</div>}
    </div>
  );
}

export function Notice({ tone = "info", children, className }: { tone?: "info" | "warning" | "error" | "success"; children: ReactNode; className?: string }) {
  const map = {
    info: "border-rule bg-sunk text-ink-2",
    warning: "border-marigold/40 bg-marigold-wash text-ink",
    error: "border-danger/30 bg-danger-wash text-danger",
    success: "border-leaf/30 bg-leaf-wash text-leaf",
  };
  return (
    <div role={tone === "error" ? "alert" : undefined} className={cn("flex gap-2 rounded-[var(--radius-control)] border px-3 py-2 text-[13px]", map[tone], className)}>
      {tone !== "info" && tone !== "success" && <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />}
      <div>{children}</div>
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-[13px] text-muted" role="status">
      <Loader2 className="size-4 animate-spin" aria-hidden /> {label}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs }: { value: T; onChange: (v: T) => void; tabs: { value: T; label: string; count?: number }[] }) {
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-rule">
      {tabs.map((t) => (
        <button
          key={t.value}
          role="tab"
          aria-selected={value === t.value}
          onClick={() => onChange(t.value)}
          className={cn(
            "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm",
            value === t.value ? "border-ink font-semibold text-ink" : "border-transparent text-muted hover:text-ink",
          )}
        >
          {t.label}
          {t.count !== undefined && <span className="ml-1.5 rounded-full bg-sunk px-1.5 text-[11px] tabular text-ink-2">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn("relative h-5 w-9 rounded-full transition-colors disabled:opacity-50", checked ? "bg-leaf" : "bg-rule-strong")}
    >
      <span className={cn("absolute top-0.5 size-4 rounded-full bg-white transition-transform", checked ? "translate-x-4" : "translate-x-0.5")} />
    </button>
  );
}

export function Drawer({ open, onClose, title, children, width = "max-w-xl" }: { open: boolean; onClose: () => void; title: string; children: ReactNode; width?: string }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={title}>
      <button className="absolute inset-0 bg-ink/30" aria-label="Close" onClick={onClose} />
      <div className={cn("relative flex h-full w-full flex-col bg-surface shadow-2xl", width)}>
        <div className="flex items-center justify-between border-b border-rule px-5 py-3.5">
          <h2 className="text-base font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded p-1 text-muted hover:bg-sunk" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-2 text-[13px]">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Table({ head, children, className }: { head: ReactNode[]; children: ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full text-left text-[13px]">
        <thead>
          <tr className="border-b border-rule text-muted">
            {head.map((h, i) => (
              <th key={i} className="whitespace-nowrap px-3 py-2 font-medium first:pl-0 last:pr-0">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="[&_td]:px-3 [&_td]:py-2.5 [&_td:first-child]:pl-0 [&_td:last-child]:pr-0 [&_tr]:border-b [&_tr]:border-rule [&_tr:last-child]:border-0">
          {children}
        </tbody>
      </table>
    </div>
  );
}
