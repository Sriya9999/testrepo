"use client";

import { formatKpi, type Kpi } from "@marketingos/api-client";
import { useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Field, Input, KeyValue, Notice, PageHeader, Panel, ProvenanceMark, Select, Spinner, StatusBadge, Table, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan, useWorkspaceQuery } from "@/lib/hooks";
import { useAuth } from "@/lib/store";
import type { ClientRow } from "../page";

export default function ClientWorkspacePage() {
  const { clientId } = useParams<{ clientId: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const setWorkspace = useAuth((s) => s.setWorkspace);
  const canManage = useCan("clients:manage");
  const canAllocate = useCan("credits:allocate");
  const { data: c } = useApiQuery<ClientRow>(`/agency/clients/${clientId}`);
  const wsId = c?.workspace_id;
  const { data: brands } = useWorkspaceQuery<{ name: string; voice: string; colors: string[] }[]>(wsId, "/brands");
  const { data: overview } = useWorkspaceQuery<{ kpis: Record<string, Kpi>; currency: string }>(wsId, "/analytics/overview");
  const { data: approvals } = useWorkspaceQuery<{ id: string; title: string; status: string }[]>(wsId, "/approvals", { status: "pending" });
  const { data: team } = useApiQuery<{ members: { user_id: string; email: string; full_name: string; role_label: string; inherited: boolean }[] }>(wsId ? `/workspaces/${wsId}/members` : null);
  const [amount, setAmount] = useState("100");
  const [status, setStatus] = useState("");
  const [notes, setNotes] = useState<string | null>(null);
  const [error, setError] = useState("");
  const m = useApiMutation((fn: () => Promise<unknown>) => fn(), ["/agency", "/billing"]);
  const run = (fn: () => Promise<unknown>) => m.mutate(fn, { onError: (e) => setError(errorMessage(e)), onSuccess: () => setError("") });
  if (!c) return <Spinner />;
  const open = () => { setWorkspace(c.workspace_id); qc.clear(); router.push("/dashboard"); };

  return (
    <>
      <PageHeader title={c.name} description={c.industry ?? undefined} actions={<Button variant="primary" onClick={open}>Open client workspace</Button>} />
      {error && <Notice tone="error" className="mb-4">{error}</Notice>}
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Profile">
          <KeyValue items={[["Status", <StatusBadge key="s" status={c.status === "active" ? "active" : c.status} />], ["Contact", [c.contact_name, c.contact_email].filter(Boolean).join(" · ") || "—"],
            ["Account manager", c.account_manager?.name ?? "Unassigned"], ["Connected", c.connected_platforms.join(", ") || "None"], ["Brand", brands?.[0] ? `${brands[0].name}${brands[0].voice ? ` · ${brands[0].voice}` : ""}` : "—"]]} />
          {canManage && (
            <div className="mt-4 space-y-3 border-t border-rule pt-4">
              <div className="flex items-end gap-2">
                <Field label="Status" className="flex-1"><Select value={status || c.status} onChange={(e) => setStatus(e.target.value)} options={["active", "paused", "archived"].map((s) => ({ value: s, label: s[0].toUpperCase() + s.slice(1) }))} /></Field>
                <Button onClick={() => run(() => api.patch(`/agency/clients/${c.id}`, { status: status || c.status }))}>Save</Button>
              </div>
              <Field label="Notes"><Textarea rows={3} value={notes ?? c.notes} onChange={(e) => setNotes(e.target.value)} /></Field>
              {notes !== null && <Button size="sm" onClick={() => run(() => api.patch(`/agency/clients/${c.id}`, { notes }))}>Save notes</Button>}
            </div>
          )}
        </Panel>
        <Panel title="Last 30 days">
          {overview ? (
            <Table head={["", "Metric", "Value"]}>
              {(["spend", "conversions", "cpa", "organic_traffic", "engagement", "seo_score"] as const).map((k) => (
                <tr key={k}><td><ProvenanceMark kind={overview.kpis[k].kind} /></td><td className="capitalize">{k.replace("_", " ")}</td><td className="tabular">{formatKpi(overview.kpis[k], overview.currency)}</td></tr>
              ))}
            </Table>
          ) : <Spinner />}
        </Panel>
        <Panel title="Credits" description="Move credits between your agency wallet and this client.">
          <p className="mb-3 text-2xl font-bold tabular">{c.credit_balance} <span className="text-sm font-normal text-muted">credits</span></p>
          {canAllocate && (
            <div className="flex items-end gap-2">
              <Field label="Amount" className="w-32"><Input type="number" min={1} value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
              <Button onClick={() => run(() => api.post(`/agency/clients/${c.id}/credits`, { amount: Number(amount), direction: "to_client" }))}>Give to client</Button>
              <Button variant="ghost" onClick={() => run(() => api.post(`/agency/clients/${c.id}/credits`, { amount: Number(amount), direction: "to_agency" }))}>Take back</Button>
            </div>
          )}
        </Panel>
        <Panel title="Waiting for approval">
          {approvals?.length ? <ul className="space-y-1.5 text-[13px]">{approvals.map((a) => <li key={a.id}>{a.title}</li>)}</ul> : <p className="text-[13px] text-muted">Nothing pending.</p>}
        </Panel>
        <Panel title="Team" className="lg:col-span-2">
          <Table head={["Person", "Role", ""]}>
            {(team?.members ?? []).map((m) => <tr key={m.user_id}><td>{m.full_name || m.email}<span className="block text-xs text-muted">{m.email}</span></td><td>{m.role_label}</td><td className="text-xs text-muted">{m.inherited ? "via agency" : ""}</td></tr>)}
          </Table>
          <p className="mt-3 text-xs text-muted">Invite client approvers and assign staff from the client workspace's Settings → Team.</p>
        </Panel>
      </div>
    </>
  );
}
