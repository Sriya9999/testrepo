"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Button, Drawer, Empty, Field, Input, Notice, PageHeader, Panel, Select, StatusBadge, Table, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan, useWorkspace } from "@/lib/hooks";
import { useAuth } from "@/lib/store";

export interface ClientRow { id: string; name: string; industry: string | null; status: string; workspace_id: string; contact_name: string | null; contact_email: string | null; notes: string;
  account_manager: { id: string; name: string } | null; connected_platforms: string[]; subscription_status: string | null; credit_balance: number; last_activity_at: string | null }

export default function ClientsPage() {
  const { data: ws } = useWorkspace();
  const canManage = useCan("clients:manage");
  const { data: clients } = useApiQuery<ClientRow[]>(ws?.kind === "agency" ? "/agency/clients" : null);
  const { data: members } = useApiQuery<{ members: { user_id: string; full_name: string; email: string }[] }>(ws ? `/workspaces/${ws.id}/members` : null);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [form, setForm] = useState({ name: "", industry: "", contact_name: "", contact_email: "", account_manager_id: "", notes: "" });
  const [error, setError] = useState("");
  const qc = useQueryClient();
  const setUser = useAuth((s) => s.setUser);
  const create = useApiMutation(() => api.post("/agency/clients", { ...form, account_manager_id: form.account_manager_id || null, contact_email: form.contact_email || null }), ["/agency"]);

  if (ws && ws.kind !== "agency") return <><PageHeader title="Clients" /><Empty title="Clients live in your agency workspace" body="Switch to the agency workspace from the menu to manage clients." /></>;
  const rows = (clients ?? []).filter((c) => c.name.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <PageHeader title="Clients" description="Each client has its own isolated workspace: brand, integrations, approvals, team and credits."
        actions={canManage && <Button variant="primary" onClick={() => setOpen(true)}>Add client</Button>} />
      <Panel>
        <div className="border-b border-rule p-3"><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search clients" aria-label="Search clients" className="max-w-xs" /></div>
        {!rows.length ? <div className="p-6"><Empty title="No clients yet" body="Add your first client to give them a workspace." /></div> : (
          <div className="px-4"><Table head={["Client", "Status", "Account manager", "Connected", "Subscription", "Credits", "Last activity"]}>
            {rows.map((c) => (
              <tr key={c.id}>
                <td><Link href={`/agency/clients/${c.id}`} className="font-medium hover:underline">{c.name}</Link><span className="block text-xs text-muted">{c.industry}</span></td>
                <td><StatusBadge status={c.status === "active" ? "active" : c.status} /></td>
                <td>{c.account_manager?.name ?? <span className="text-muted">Unassigned</span>}</td>
                <td className="text-[13px]">{c.connected_platforms.length ? c.connected_platforms.map((p) => p.replace("_", " ")).join(", ") : <span className="text-muted">None</span>}</td>
                <td className="capitalize">{c.subscription_status ?? "—"}</td>
                <td className="tabular">{c.credit_balance}</td>
                <td className="text-[13px] text-muted">{c.last_activity_at ? new Date(c.last_activity_at).toLocaleDateString("en-IN") : "—"}</td>
              </tr>
            ))}
          </Table></div>
        )}
      </Panel>
      <Drawer open={open} onClose={() => setOpen(false)} title="Add client">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(undefined, { onSuccess: async () => { setOpen(false); setUser(await api.get("/users/me")); qc.invalidateQueries({ queryKey: ["workspace"] }); }, onError: (er) => setError(errorMessage(er)) }); }}>
          {error && <Notice tone="error">{error}</Notice>}
          <Field label="Client name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
          <Field label="Industry"><Input value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Contact name"><Input value={form.contact_name} onChange={(e) => setForm({ ...form, contact_name: e.target.value })} /></Field>
            <Field label="Contact email"><Input type="email" value={form.contact_email} onChange={(e) => setForm({ ...form, contact_email: e.target.value })} /></Field>
          </div>
          <Field label="Account manager"><Select value={form.account_manager_id} onChange={(e) => setForm({ ...form, account_manager_id: e.target.value })}
            options={[{ value: "", label: "Assign later" }, ...(members?.members ?? []).map((m) => ({ value: m.user_id, label: m.full_name || m.email }))]} /></Field>
          <Field label="Notes"><Textarea rows={3} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
          <Button variant="primary" loading={create.isPending}>Create client workspace</Button>
        </form>
      </Drawer>
    </>
  );
}
