"use client";

import type { Approval } from "@marketingos/api-client";
import { Check, Circle, Loader2, Minus, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ApprovalItem } from "@/components/approval";
import { Button, cn, Empty, Notice, PageHeader, Panel, Select, StatusBadge, Tag, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery } from "@/lib/hooks";

interface Plan {
  parsed: Record<string, number | boolean | string | null>;
  steps: { agent: string; title: string; requires_approval?: boolean }[];
  estimate: { total: number; items: { operation: string; quantity: number; credits: number }[] };
  connected: Record<string, boolean>;
  balance: number;
}
interface Run {
  id: string; instruction: string; status: string; credits_used: number; error: string | null; created_at: string;
  output?: { content_ids?: string[]; post_ids?: string[]; campaign_ids?: string[]; strategy?: Record<string, any> };
  tasks?: { id: string; agent: string; title: string; status: string; credits_used: number }[];
}
interface Log { id: string; agent: string; level: string; message: string; created_at: string }

const SUGGESTIONS = [
  "Create 15 Instagram posts, 4 Reels and a Meta Ads campaign for next month",
  "Plan 2 weeks of Instagram content for our weekend offer",
  "Grow my business over the next 30 days: Google visibility, AI search, Instagram and ads with ₹800 per day",
  "Prepare a Google search campaign for our main service",
];
const TERMINAL = ["completed", "failed", "cancelled", "awaiting_approval"];

function TaskIcon({ status }: { status: string }) {
  if (status === "done") return <Check className="size-3.5 text-leaf" aria-label="Done" />;
  if (status === "running") return <Loader2 className="size-3.5 animate-spin" aria-label="Running" />;
  if (status === "failed") return <X className="size-3.5 text-danger" aria-label="Failed" />;
  if (status === "skipped") return <Minus className="size-3.5 text-faint" aria-label="Skipped" />;
  return <Circle className="size-3.5 text-faint" aria-label="Waiting" />;
}

function RunView({ runId }: { runId: string }) {
  const { data: run } = useApiQuery<Run>(`/agents/runs/${runId}`, undefined, {
    refetchInterval: (q) => (q.state.data && TERMINAL.includes((q.state.data as Run).status) ? false : 1500),
  });
  const { data: logs } = useApiQuery<Log[]>(`/agents/runs/${runId}/logs`, undefined, {
    refetchInterval: run && TERMINAL.includes(run.status) ? false : 1500,
  });
  const { data: approvals } = useApiQuery<Approval[]>("/approvals", { status: "all", group_id: runId }, { enabled: Boolean(run && TERMINAL.includes(run.status)) });
  const cancel = useApiMutation(() => api.post(`/agents/runs/${runId}/cancel`), ["/agents"]);
  const bulk = useApiMutation((ids: string[]) => api.post("/approvals/bulk-approve", { ids }), ["/approvals", "/agents"]);
  if (!run) return null;
  const pending = approvals?.filter((a) => a.status === "pending" && a.can_decide) ?? [];

  return (
    <div className="space-y-5">
      <Panel title={<span className="flex items-center gap-2">Workflow <StatusBadge status={run.status} /></span>}
        description={`“${run.instruction}”`}
        actions={!TERMINAL.includes(run.status) && <Button size="sm" variant="danger" onClick={() => cancel.mutate(undefined)}>Cancel run</Button>}>
        {run.error && <Notice tone="error" className="mb-3">{run.error}</Notice>}
        <div className="grid gap-6 md:grid-cols-2">
          <ol className="space-y-2" aria-label="Agent steps">
            {(run.tasks ?? []).map((t) => (
              <li key={t.id} className="flex items-start gap-2 text-[13px]">
                <span className="mt-0.5"><TaskIcon status={t.status} /></span>
                <span className="flex-1"><span className="text-muted">{t.agent.replace("_", " ")} · </span>{t.title}</span>
                {t.credits_used > 0 && <span className="text-xs tabular text-muted">{t.credits_used} cr</span>}
              </li>
            ))}
            {!run.tasks?.length && <li className="text-[13px] text-muted">Starting…</li>}
          </ol>
          <div className="max-h-72 overflow-y-auto rounded-[var(--radius-control)] bg-sunk p-3" aria-live="polite" aria-label="Execution log">
            {(logs ?? []).map((l) => (
              <p key={l.id} className={cn("mb-1.5 text-[12.5px] leading-snug", l.level === "warning" && "text-marigold-deep", l.level === "error" && "text-danger")}>
                <span className="font-medium">{l.agent.replace("_", " ")}:</span> {l.message}
              </p>
            ))}
            {!logs?.length && <p className="text-[12.5px] text-muted">Waiting for the first agent…</p>}
          </div>
        </div>
        <p className="mt-4 text-xs text-muted">{run.credits_used} credits used</p>
      </Panel>

      {run.output?.strategy && (
        <Panel title="Strategy">
          <p className="mb-3 text-[14px]">{run.output.strategy.objective}</p>
          <div className="grid gap-4 text-[13px] md:grid-cols-3">
            <div><p className="mb-1 font-medium">Content pillars</p><ul className="list-disc space-y-0.5 pl-4">{(run.output.strategy.pillars ?? []).map((p: string) => <li key={p}>{p}</li>)}</ul></div>
            <div><p className="mb-1 font-medium">Weekly themes</p><ul className="space-y-0.5">{(run.output.strategy.weekly_themes ?? []).map((w: { week: number; theme: string }) => <li key={w.week}>Week {w.week}: {w.theme}</li>)}</ul></div>
            <div><p className="mb-1 font-medium">Watch</p><ul className="list-disc space-y-0.5 pl-4">{(run.output.strategy.kpis_to_watch ?? []).map((k: string) => <li key={k}>{k}</li>)}</ul></div>
          </div>
        </Panel>
      )}

      {run.output && (run.output.content_ids?.length || run.output.campaign_ids?.length) ? (
        <p className="flex flex-wrap gap-3 text-[13px]">
          {!!run.output.content_ids?.length && <Link className="underline" href="/content-studio">{run.output.content_ids.length} drafts in Content studio</Link>}
          {!!run.output.post_ids?.length && <Link className="underline" href="/social/calendar">{run.output.post_ids.length} posts on the calendar</Link>}
          {!!run.output.campaign_ids?.length && <Link className="underline" href="/advertising/meta">{run.output.campaign_ids.length} campaign drafts</Link>}
        </p>
      ) : null}

      {approvals && approvals.length > 0 && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-bold tracking-tight">Ready for your sign-off</h2>
            {pending.length > 1 && <Button variant="approve" loading={bulk.isPending} onClick={() => bulk.mutate(pending.map((a) => a.id))}>Approve all {pending.length}</Button>}
          </div>
          {approvals.map((a) => <ApprovalItem key={a.id} a={a} />)}
        </section>
      )}
    </div>
  );
}

export default function AssistantPage() {
  const [instruction, setInstruction] = useState("");
  const [brandId, setBrandId] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: brands } = useApiQuery<{ id: string; name: string }[]>("/brands");
  const { data: runs } = useApiQuery<Run[]>("/agents/runs");

  const preview = async () => {
    setError(""); setBusy(true); setRunId(null);
    try { setPlan(await api.post<Plan>("/agents/plan", { instruction, brand_id: brandId || null })); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };
  const start = async () => {
    setError(""); setBusy(true);
    try {
      const r = await api.post<Run>("/agents/run", { instruction, brand_id: brandId || null });
      setRunId(r.id); setPlan(null);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader title="AI assistant" description="Describe what you want. The assistant breaks it into tasks for specialised agents; anything that publishes or spends comes back to you for approval." />
      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        <div className="space-y-5">
          <Panel>
            <div className="space-y-3 p-4">
              <Textarea rows={3} value={instruction} onChange={(e) => setInstruction(e.target.value)} aria-label="Instruction"
                placeholder="Create 15 Instagram posts, 4 Reels and a Meta Ads campaign for November." />
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => setInstruction(s)} className="rounded-full border border-rule px-2.5 py-1 text-left text-xs text-ink-2 hover:border-rule-strong hover:bg-sunk">{s}</button>
                ))}
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-rule pt-3">
                <Select aria-label="Brand" className="w-56" value={brandId} onChange={(e) => setBrandId(e.target.value)}
                  options={[{ value: "", label: "Default brand" }, ...(brands ?? []).map((b) => ({ value: b.id, label: b.name }))]} />
                <Button variant="primary" loading={busy && !plan} disabled={instruction.trim().length < 5} onClick={preview}>Review plan</Button>
              </div>
            </div>
          </Panel>
          {error && <Notice tone="error">{error}</Notice>}
          {plan && (
            <Panel title="Proposed plan" description="Nothing runs until you start it. Credits are charged only for work that completes.">
              <ol className="space-y-2">
                {plan.steps.map((s, i) => (
                  <li key={i} className="flex items-start gap-3 text-[14px]">
                    <span className="grid size-5 shrink-0 place-items-center rounded-full bg-sunk text-[11px] font-semibold tabular">{i + 1}</span>
                    <span className="flex-1">{s.title} <span className="text-xs text-muted">· {s.agent.replace("_", " ")} agent</span></span>
                    {s.requires_approval && <Tag>needs approval</Tag>}
                  </li>
                ))}
              </ol>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-rule pt-3">
                <p className="text-[13px]">Estimated <b className="tabular">{plan.estimate.total}</b> credits · balance <b className="tabular">{plan.balance}</b>
                  {plan.estimate.total > plan.balance && <span className="block text-xs text-marigold-deep">The run will stop cleanly when credits run out; you keep everything finished so far.</span>}
                </p>
                <div className="flex gap-2">
                  <Button variant="ghost" onClick={() => setPlan(null)}>Edit request</Button>
                  <Button variant="primary" loading={busy} onClick={start}>Start</Button>
                </div>
              </div>
            </Panel>
          )}
          {runId && <RunView runId={runId} />}
          {!plan && !runId && <Empty title="No run selected" body="Review a plan above, or open a past run from the list." />}
        </div>
        <aside>
          <Panel title="Past runs">
            {runs?.length ? (
              <ul className="-my-2 divide-y divide-rule">
                {runs.map((r) => (
                  <li key={r.id}>
                    <button onClick={() => { setRunId(r.id); setPlan(null); }} className={cn("w-full py-2 text-left", r.id === runId && "font-semibold")}>
                      <span className="line-clamp-2 text-[13px]">{r.instruction}</span>
                      <span className="mt-1 flex items-center gap-2 text-xs text-muted"><StatusBadge status={r.status} /> {new Date(r.created_at).toLocaleDateString("en-IN")}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-muted">Your runs will appear here.</p>}
          </Panel>
        </aside>
      </div>
    </>
  );
}
