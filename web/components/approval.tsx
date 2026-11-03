"use client";

import { formatMoney, type Approval } from "@marketingos/api-client";
import { Bot, Megaphone, PenSquare, Send } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation } from "@/lib/hooks";
import { Button, cn, Notice, StatusBadge, Tag, Textarea } from "./ui";

const ICONS: Record<string, typeof Bot> = { content: PenSquare, social_post: Send, campaign: Megaphone };

function Preview({ a }: { a: Approval }) {
  const p = a.preview;
  if (!p) return null;
  if (p.type === "social_post") {
    return (
      <div className="flex gap-3">
        {p.media?.[0]?.url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={p.media[0].url} alt="" className="size-20 shrink-0 rounded-md border border-rule object-cover" />
        )}
        <p className="line-clamp-4 whitespace-pre-line text-[13px] text-ink-2">{p.caption}</p>
      </div>
    );
  }
  if (p.type === "content") {
    const b = p.body ?? {};
    const text = b.caption ?? b.primary_text ?? b.short_answer ?? b.title ?? b.hero?.headline ?? (b.headlines ?? []).join(" · ");
    return <p className="line-clamp-4 whitespace-pre-line text-[13px] text-ink-2">{text}</p>;
  }
  if (p.type === "campaign") {
    const c = p.campaign ?? {};
    const rows: [string, string][] = [];
    if (c.objective) rows.push(["Objective", c.objective]);
    if (c.daily_budget_minor) rows.push(["Daily budget", formatMoney(c.daily_budget_minor, c.currency)]);
    if (c.start_date) rows.push(["Runs", `${c.start_date}${c.end_date ? ` → ${c.end_date}` : ""}`]);
    if (p.changes) Object.entries(p.changes).forEach(([k, v]) => rows.push([k.replace(/_/g, " "), k.includes("budget") ? formatMoney(v as number, c.currency) : JSON.stringify(v)]));
    if (p.operation === "set_status") rows.push(["Change", p.payload?.status ?? ""]);
    if (c.config?.copy?.primary_text) rows.push(["Ad copy", c.config.copy.primary_text]);
    if (c.config?.ad_groups) rows.push(["Ad groups", c.config.ad_groups.map((g: { name: string }) => g.name).join(", ")]);
    return (
      <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 text-[13px]">
        {rows.map(([k, v]) => (
          <div key={k} className="contents"><dt className="capitalize text-muted">{k}</dt><dd className="line-clamp-2">{v}</dd></div>
        ))}
      </dl>
    );
  }
  return null;
}

/** One proposed action. The marigold edge marks items that are waiting on a person. */
export function ApprovalItem({ a, compact = false }: { a: Approval; compact?: boolean }) {
  const [note, setNote] = useState("");
  const [mode, setMode] = useState<"idle" | "changes">("idle");
  const decide = useApiMutation((d: { action: string; note?: string }) => api.post(`/approvals/${a.id}/${d.action}`, { note: d.note }),
    ["/approvals", "/dashboard", "/content", "/social", "/ads", "/agents"]);
  const Icon = ICONS[a.resource_type] ?? Bot;
  const pending = a.status === "pending";

  return (
    <article className={cn("rounded-[var(--radius-panel)] border bg-surface", pending ? "border-marigold/60 border-l-4 border-l-marigold" : "border-rule")}>
      <div className="flex flex-wrap items-start gap-3 p-4">
        <Icon className="mt-0.5 size-4 shrink-0 text-ink-2" aria-hidden />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold leading-snug">{a.title}</h3>
            {!pending && <StatusBadge status={a.status} />}
          </div>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            <span>{a.action_label}</span>
            {a.client && <span>{a.client}</span>}
            {a.requested_by_agent ? <Tag tone="ai">Prepared by the {a.requested_by_agent.replace("_", " ")} agent</Tag> : a.requested_by && <span>Requested by {a.requested_by}</span>}
            <span>{new Date(a.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</span>
          </p>
          {!compact && <Preview a={a} />}
          {!compact && (a.ai_reasoning || a.expected_outcome) && (
            <div className="grid gap-2 border-t border-rule pt-2 text-[13px] sm:grid-cols-2">
              {a.ai_reasoning && <p><span className="text-muted">Why: </span>{a.ai_reasoning}</p>}
              {a.expected_outcome && <p><span className="text-muted">Expected: </span>{a.expected_outcome}</p>}
            </div>
          )}
          {a.decision_note && <p className="text-[13px]"><span className="text-muted">Note from {a.decided_by}: </span>{a.decision_note}</p>}
        </div>
        {a.budget_impact_minor !== null && (
          <div className="text-right">
            <p className="text-xs text-muted">Budget impact</p>
            <p className="text-lg font-bold tabular">{formatMoney(a.budget_impact_minor, a.currency ?? "INR")}</p>
          </div>
        )}
      </div>
      {pending && a.can_decide && (
        <div className="space-y-2 border-t border-rule px-4 py-3">
          {decide.error && <Notice tone="error">{errorMessage(decide.error)}</Notice>}
          {mode === "changes" && (
            <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What should change?" autoFocus />
          )}
          <div className="flex flex-wrap gap-2">
            {mode === "idle" ? (
              <>
                <Button variant="approve" size="sm" loading={decide.isPending} onClick={() => decide.mutate({ action: "approve" })}>Approve</Button>
                <Button size="sm" onClick={() => setMode("changes")}>Request changes</Button>
                <Button size="sm" variant="danger" onClick={() => decide.mutate({ action: "reject" })}>Reject</Button>
              </>
            ) : (
              <>
                <Button size="sm" variant="primary" disabled={!note} loading={decide.isPending} onClick={() => decide.mutate({ action: "request-changes", note })}>Send back</Button>
                <Button size="sm" variant="ghost" onClick={() => setMode("idle")}>Cancel</Button>
              </>
            )}
          </div>
        </div>
      )}
      {pending && !a.can_decide && <p className="border-t border-rule px-4 py-2 text-xs text-muted">Waiting for someone who can approve this.</p>}
    </article>
  );
}
