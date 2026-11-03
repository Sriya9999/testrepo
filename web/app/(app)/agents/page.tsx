"use client";

import Link from "next/link";
import { Notice, PageHeader, Panel, StatusBadge, Table, Tag, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan } from "@/lib/hooks";

interface Agent { id: string; name: string; function: string; status: string; requires: string | null; enabled: boolean; credits_last_30_days: number; tasks_run: number;
  actions: { action: string; policy: string }[] }
interface Run { id: string; instruction: string; status: string; credits_used: number; created_at: string }
const pretty = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export default function AgentsPage() {
  const canManage = useCan("workspace:manage");
  const { data } = useApiQuery<{ agents: Agent[]; provider: string }>("/agents");
  const { data: runs } = useApiQuery<Run[]>("/agents/runs");
  const toggle = useApiMutation((a: { id: string; enabled: boolean }) => api.patch(`/agents/${a.id}`, { enabled: a.enabled }), ["/agents"]);
  return (
    <>
      <PageHeader title="AI agents" description="Specialised agents the orchestrator calls on. Each can only take the actions listed; anything marked “needs approval” comes to you first." />
      {toggle.error && <Notice tone="error" className="mb-4">{errorMessage(toggle.error)}</Notice>}
      {data?.provider === "offline" && <Notice tone="warning" className="mb-4">Agents are running on offline templates. Connect an AI model (OPENAI_API_KEY on the server) for full-quality strategy and copy.</Notice>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data?.agents.map((a) => (
          <Panel key={a.id}>
            <div className="space-y-3 p-4">
              <div className="flex items-start justify-between gap-2">
                <div><h2 className="font-semibold">{a.name}</h2><p className="text-[13px] text-muted">{a.function}</p></div>
                {a.id !== "orchestrator" && <Toggle checked={a.enabled} disabled={!canManage} onChange={(v) => toggle.mutate({ id: a.id, enabled: v })} label={`${a.name} enabled`} />}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={a.status === "ready" ? "ready" : a.status} label={a.status === "needs_integration" ? `Connect ${pretty(a.requires ?? "")}` : undefined} />
                <span className="text-xs text-muted tabular">{a.tasks_run} tasks · {a.credits_last_30_days} credits in 30 days</span>
              </div>
              <ul className="space-y-1 border-t border-rule pt-2 text-[13px]">
                {a.actions.map((x) => (
                  <li key={x.action} className="flex justify-between gap-2"><span>{pretty(x.action)}</span>
                    {x.policy === "automatic" ? <span className="text-xs text-muted">automatic</span> : <Tag>needs approval</Tag>}</li>
                ))}
              </ul>
            </div>
          </Panel>
        ))}
      </div>
      <Panel title="Execution history" className="mt-6">
        <Table head={["Instruction", "Status", "Credits", "Started"]}>
          {(runs ?? []).map((r) => (
            <tr key={r.id}><td className="max-w-lg"><Link href="/assistant" className="line-clamp-1 hover:underline">{r.instruction}</Link></td><td><StatusBadge status={r.status} /></td>
              <td className="tabular">{r.credits_used}</td><td className="text-[13px] text-muted">{new Date(r.created_at).toLocaleString("en-IN")}</td></tr>
          ))}
        </Table>
        {!runs?.length && <p className="text-[13px] text-muted">No runs yet. Start one from the AI assistant.</p>}
      </Panel>
    </>
  );
}
