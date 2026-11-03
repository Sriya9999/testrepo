"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, Drawer, Field, Input, Notice, PageHeader, Panel, StatusBadge, Tag } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan } from "@/lib/hooks";

interface Account { id: string; display_name: string; mode: string; status: string; scopes: string[]; last_sync_at: string | null; last_error: string | null }
interface Integration { provider: string; name: string; category: string; auth: string; description: string; configured: boolean; sandbox_available: boolean; status: string; accounts: Account[];
  last_sync_at: string | null; details?: Record<string, unknown> }

function Integrations() {
  const params = useSearchParams();
  const canManage = useCan("integrations:manage");
  const { data } = useApiQuery<Integration[]>("/integrations");
  const [creds, setCreds] = useState<Integration | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ tone: "error" | "success"; text: string } | null>(
    params.get("error") ? { tone: "error", text: params.get("error")! } : params.get("connected") ? { tone: "success", text: `${params.get("connected")} connected.` } : null);
  const m = useApiMutation((fn: () => Promise<unknown>) => fn(), ["/integrations", "/ads", "/social"]);
  const run = (fn: () => Promise<unknown>, ok?: string) => m.mutate(fn, { onError: (e) => setMsg({ tone: "error", text: errorMessage(e) }), onSuccess: () => ok && setMsg({ tone: "success", text: ok }) });
  const connect = (i: Integration, mode: "live" | "sandbox") => {
    if (mode === "live" && i.auth === "credentials") { setForm({}); setCreds(i); return; }
    run(async () => {
      const r = await api.post<{ authorize_url?: string }>(`/integrations/${i.provider}/connect`, { mode });
      if (r.authorize_url) window.location.href = r.authorize_url;
    }, mode === "sandbox" ? `${i.name} sandbox connected.` : undefined);
  };

  return (
    <>
      <PageHeader title="Integrations" description="Connections are per workspace. Access tokens are encrypted on the server and never sent to your browser." />
      {msg && <Notice tone={msg.tone} className="mb-4">{msg.text}</Notice>}
      <div className="grid gap-4 md:grid-cols-2">
        {data?.map((i) => (
          <Panel key={i.provider}>
            <div className="space-y-3 p-4">
              <div className="flex items-start justify-between gap-3">
                <div><h2 className="font-semibold">{i.name}</h2><p className="text-[13px] text-muted">{i.description}</p></div>
                <StatusBadge status={i.status === "not_connected" ? "draft" : i.status} label={i.status === "not_connected" ? "Not connected" : undefined} />
              </div>
              {i.provider === "ai" ? (
                <p className="text-[13px]">Text: <b>{String(i.details?.text)}</b> · Perplexity: <b>{i.details?.perplexity ? "on" : "off"}</b> · Keyword data: <b>{String(i.details?.keyword_data ?? "none")}</b></p>
              ) : (
                <>
                  {i.accounts.map((a) => (
                    <div key={a.id} className="rounded-md border border-rule p-2.5 text-[13px]">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium">{a.display_name} {a.mode === "sandbox" && <Tag tone="sandbox">sandbox</Tag>}</span>
                        {canManage && <span className="flex gap-1">
                          <Button size="sm" variant="ghost" onClick={() => run(() => api.post(`/integrations/accounts/${a.id}/sync`), "Sync started.")}>Sync</Button>
                          {i.auth !== "credentials" && <Button size="sm" variant="ghost" onClick={() => connect(i, a.mode as "live" | "sandbox")}>Reconnect</Button>}
                          <Button size="sm" variant="ghost" onClick={() => confirm(`Disconnect ${a.display_name}? Its stored credentials are deleted.`) && run(() => api.del(`/integrations/accounts/${a.id}`), "Disconnected.")}>Disconnect</Button>
                        </span>}
                      </div>
                      <p className="text-xs text-muted">Last sync: {a.last_sync_at ? new Date(a.last_sync_at).toLocaleString("en-IN") : "never"}{a.scopes.length ? ` · ${a.scopes.length} permissions` : ""}</p>
                      {a.last_error && <p className="text-xs text-danger">{a.last_error}</p>}
                    </div>
                  ))}
                  {canManage && (
                    <div className="flex flex-wrap gap-2">
                      <Button variant="primary" size="sm" disabled={!i.configured} onClick={() => connect(i, "live")}>{i.accounts.length ? "Connect another" : "Connect"}</Button>
                      {i.sandbox_available && <Button size="sm" onClick={() => connect(i, "sandbox")}>Use sandbox</Button>}
                    </div>
                  )}
                  {!i.configured && <p className="text-xs text-muted">Not configured on this server yet: the operator needs to add the app credentials.</p>}
                </>
              )}
            </div>
          </Panel>
        ))}
      </div>
      <Drawer open={Boolean(creds)} onClose={() => setCreds(null)} title={`Connect ${creds?.name}`}>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.post(`/integrations/${creds!.provider}/connect`, { mode: "live", credentials: form }); setCreds(null); }, `${creds!.name} connected.`); }}>
          {creds?.provider === "wordpress" ? (
            <>
              <Field label="Site URL"><Input value={form.site_url ?? ""} onChange={(e) => setForm({ ...form, site_url: e.target.value })} placeholder="https://yourblog.in" required /></Field>
              <Field label="Username"><Input value={form.username ?? ""} onChange={(e) => setForm({ ...form, username: e.target.value })} required /></Field>
              <Field label="Application password" hint="Create one under Users → Profile → Application passwords."><Input type="password" value={form.application_password ?? ""} onChange={(e) => setForm({ ...form, application_password: e.target.value })} required /></Field>
            </>
          ) : (
            <>
              <Field label="Store domain"><Input value={form.shop_domain ?? ""} onChange={(e) => setForm({ ...form, shop_domain: e.target.value })} placeholder="yourstore.myshopify.com" required /></Field>
              <Field label="Admin API access token"><Input type="password" value={form.access_token ?? ""} onChange={(e) => setForm({ ...form, access_token: e.target.value })} required /></Field>
            </>
          )}
          <Button variant="primary" loading={m.isPending}>Connect</Button>
        </form>
      </Drawer>
    </>
  );
}

export default function IntegrationsPage() {
  return <Suspense><Integrations /></Suspense>;
}
