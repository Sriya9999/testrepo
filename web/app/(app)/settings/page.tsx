"use client";

import type { User, WorkspaceDetail } from "@marketingos/api-client";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Button, Field, Input, KeyValue, Notice, PageHeader, Panel, Select, Table, Tabs, Textarea, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan, useWorkspace } from "@/lib/hooks";
import { useAuth } from "@/lib/store";

type Tab = "profile" | "workspace" | "team" | "brand" | "audit";
interface Brand { id: string; name: string; industry: string | null; description: string; website_url: string | null; logo_url: string | null; colors: string[]; fonts: string[];
  target_customers: string; products: { name: string; description: string }[]; voice: string; competitor_references: string[]; prohibited_claims: string[]; approved_ctas: string[]; locations: string[] }

function useMsg() {
  const [msg, setMsg] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  return { msg, ok: (text: string) => setMsg({ tone: "success", text }), fail: (e: unknown) => setMsg({ tone: "error", text: errorMessage(e) }),
    view: msg && <Notice tone={msg.tone} className="mb-4">{msg.text}</Notice> };
}

function Profile() {
  const { user, setUser } = useAuth();
  const [name, setName] = useState(user?.full_name ?? "");
  const [mfa, setMfa] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const m = useMsg();
  if (!user) return null;
  const call = async (fn: () => Promise<unknown>, text: string) => { try { await fn(); setUser(await api.get<User>("/users/me")); m.ok(text); } catch (e) { m.fail(e); } };
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Panel title="Your profile">
        {m.view}
        <div className="space-y-3">
          <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <KeyValue items={[["Email", `${user.email}${user.email_verified ? "" : " (not verified)"}`]]} />
          <div className="flex gap-2">
            <Button variant="primary" onClick={() => call(() => api.patch("/users/me", { full_name: name }), "Saved.")}>Save</Button>
            {!user.email_verified && <Button onClick={() => call(() => api.post("/auth/resend-verification"), "Verification email sent.")}>Resend verification</Button>}
          </div>
        </div>
      </Panel>
      <Panel title="Two-factor authentication" description="Ask for a code from an authenticator app when you sign in.">
        {user.mfa_enabled ? (
          <div className="space-y-3">
            <Notice tone="success">Two-factor authentication is on.</Notice>
            <Field label="Code from your app, to turn it off"><Input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" /></Field>
            <Button variant="danger" onClick={() => call(() => api.post("/users/me/mfa/disable", { code }), "Two-factor authentication is off.")}>Turn off</Button>
          </div>
        ) : mfa ? (
          <div className="space-y-3">
            <p className="text-[13px]">Add this key to your authenticator app (or open the link on your phone), then enter the 6-digit code.</p>
            <p className="break-all rounded bg-sunk p-2 font-mono text-[13px]">{mfa.secret}</p>
            <a href={mfa.otpauth_uri} className="text-[13px] underline">Open in authenticator</a>
            <Field label="Code"><Input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" /></Field>
            <Button variant="primary" onClick={() => call(async () => { await api.post("/users/me/mfa/enable", { code }); setMfa(null); setCode(""); }, "Two-factor authentication is on.")}>Turn on</Button>
          </div>
        ) : <Button onClick={async () => { try { setMfa(await api.post("/users/me/mfa/setup")); } catch (e) { m.fail(e); } }}>Set up</Button>}
      </Panel>
    </div>
  );
}

function WorkspaceSettings({ ws }: { ws: WorkspaceDetail }) {
  const canManage = useCan("workspace:manage");
  const canDelete = useCan("workspace:delete");
  const qc = useQueryClient();
  const router = useRouter();
  const m = useMsg();
  const [f, setF] = useState({ name: ws.name, timezone: ws.timezone, currency: ws.currency, industry: ws.industry ?? "" });
  const [ap, setAp] = useState(ws.settings.approvals);
  const [limits, setLimits] = useState({ meta: String((ws.settings.spend_limits.meta_max_daily_budget_minor ?? 0) / 100), google: String((ws.settings.spend_limits.google_max_daily_budget_minor ?? 0) / 100) });
  const [wl, setWl] = useState<Record<string, string>>((ws as WorkspaceDetail & { white_label?: Record<string, string> }).white_label ?? {});
  const save = async () => {
    try {
      await api.patch(`/workspaces/${ws.id}`, { ...f, settings: { approvals: ap, spend_limits: {
        meta_max_daily_budget_minor: Math.round(Number(limits.meta) * 100), google_max_daily_budget_minor: Math.round(Number(limits.google) * 100) } } });
      if (ws.kind === "agency") await api.patch(`/workspaces/${ws.id}/white-label`, wl);
      qc.invalidateQueries({ queryKey: ["workspace"] });
      m.ok("Workspace settings saved.");
    } catch (e) { m.fail(e); }
  };
  return (
    <div className="space-y-5">
      {m.view}
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Workspace">
          <div className="space-y-3">
            <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} disabled={!canManage} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Time zone"><Input value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })} disabled={!canManage} /></Field>
              <Field label="Currency"><Select value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })} disabled={!canManage} options={["INR", "USD", "AED", "SGD", "GBP"].map((c) => ({ value: c, label: c }))} /></Field>
            </div>
            <Field label="Industry"><Input value={f.industry} onChange={(e) => setF({ ...f, industry: e.target.value })} disabled={!canManage} /></Field>
          </div>
        </Panel>
        <Panel title="Approval policy" description="What needs a second pair of eyes in this workspace.">
          <div className="space-y-3 text-[14px]">
            {([["allow_self_approval", "Let people approve their own requests", "Useful for one-person businesses. Turn off to require a second approver."],
              ["require_approval_for_pause", "Pausing a campaign needs approval", "Pauses stop spend, so by default they apply right away."],
              ["require_approval_for_budget_decrease", "Budget decreases need approval", "Increases always need approval."]] as const).map(([k, label, hint]) => (
              <label key={k} className="flex items-start gap-3">
                <Toggle checked={Boolean(ap[k])} disabled={!canManage} onChange={(v) => setAp({ ...ap, [k]: v })} label={label} />
                <span><span className="block">{label}</span><span className="block text-xs text-muted">{hint}</span></span>
              </label>
            ))}
            <div className="grid grid-cols-2 gap-3 border-t border-rule pt-3">
              <Field label={`Meta daily cap (${ws.currency})`} hint="Drafts above this are refused"><Input type="number" value={limits.meta} onChange={(e) => setLimits({ ...limits, meta: e.target.value })} disabled={!canManage} /></Field>
              <Field label={`Google daily cap (${ws.currency})`}><Input type="number" value={limits.google} onChange={(e) => setLimits({ ...limits, google: e.target.value })} disabled={!canManage} /></Field>
            </div>
          </div>
        </Panel>
        {ws.kind === "agency" && (
          <Panel title="White-label reports" description="Shown on reports you send to clients.">
            <div className="space-y-3">
              <Field label="Agency name on reports"><Input value={wl.agency_name ?? ""} onChange={(e) => setWl({ ...wl, agency_name: e.target.value })} /></Field>
              <Field label="Brand colour"><Input value={wl.primary_color ?? ""} onChange={(e) => setWl({ ...wl, primary_color: e.target.value })} placeholder="#172033" /></Field>
              <Field label="Footer"><Input value={wl.footer ?? ""} onChange={(e) => setWl({ ...wl, footer: e.target.value })} /></Field>
            </div>
          </Panel>
        )}
      </div>
      {canManage && <Button variant="primary" onClick={save}>Save settings</Button>}
      {canDelete && (
        <Panel title="Delete workspace" description="Integrations are disconnected immediately and all data is permanently deleted after 7 days.">
          <Button variant="danger" onClick={async () => {
            if (prompt(`Type ${ws.name} to delete this workspace`) !== ws.name) return;
            try { await api.del(`/workspaces/${ws.id}`); useAuth.getState().setUser(await api.get("/users/me")); router.replace("/dashboard"); } catch (e) { m.fail(e); }
          }}>Delete this workspace</Button>
        </Panel>
      )}
    </div>
  );
}

function Team({ ws }: { ws: WorkspaceDetail }) {
  const canManage = useCan("members:manage");
  const { data } = useApiQuery<{ members: { user_id: string; email: string; full_name: string; role: string; role_label: string; inherited: boolean }[]; invitations: { email: string; role: string }[];
    assignable_roles: { value: string; label: string }[] }>(`/workspaces/${ws.id}/members`);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("content_creator");
  const m = useMsg();
  const mut = useApiMutation((fn: () => Promise<unknown>) => fn(), ["/workspaces"]);
  const run = (fn: () => Promise<unknown>, text: string) => mut.mutate(fn, { onSuccess: () => m.ok(text), onError: m.fail });
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
      <Panel title="Team">
        {m.view}
        <Table head={["Person", "Role", ""]}>
          {data?.members.map((p) => (
            <tr key={p.user_id}>
              <td>{p.full_name || p.email}<span className="block text-xs text-muted">{p.email}</span></td>
              <td>{p.inherited || !canManage ? <span>{p.role_label}{p.inherited && <span className="text-xs text-muted"> (organisation)</span>}</span> : (
                <Select aria-label={`Role for ${p.email}`} className="w-48" value={p.role} onChange={(e) => run(() => api.patch(`/workspaces/${ws.id}/members/${p.user_id}`, { role: e.target.value }), "Role updated.")} options={data.assignable_roles} />
              )}</td>
              <td>{canManage && !p.inherited && <Button size="sm" variant="ghost" onClick={() => run(() => api.del(`/workspaces/${ws.id}/members/${p.user_id}`), "Removed.")}>Remove</Button>}</td>
            </tr>
          ))}
          {data?.invitations.map((i) => <tr key={i.email}><td>{i.email}<span className="block text-xs text-muted">Invited, hasn't signed up yet</span></td><td>{data.assignable_roles.find((r) => r.value === i.role)?.label}</td><td /></tr>)}
        </Table>
      </Panel>
      {canManage && (
        <Panel title="Invite someone">
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.post(`/workspaces/${ws.id}/members`, { email, role }); setEmail(""); }, "Invitation sent."); }}>
            <Field label="Email"><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
            <Field label="Role"><Select value={role} onChange={(e) => setRole(e.target.value)} options={data?.assignable_roles ?? []} /></Field>
            <Button variant="primary" className="w-full" loading={mut.isPending}>Send invite</Button>
          </form>
        </Panel>
      )}
    </div>
  );
}

function BrandSettings() {
  const canWrite = useCan("brand:write");
  const { data: brands, refetch } = useApiQuery<Brand[]>("/brands");
  const brand = brands?.[0];
  const [f, setF] = useState<Record<string, string>>({});
  const m = useMsg();
  useEffect(() => {
    if (brand) setF({ name: brand.name, industry: brand.industry ?? "", description: brand.description, website_url: brand.website_url ?? "", colors: brand.colors.join(", "), fonts: brand.fonts.join(", "),
      target_customers: brand.target_customers, products: brand.products.map((p) => p.name).join("\n"), voice: brand.voice, competitor_references: brand.competitor_references.join(", "),
      prohibited_claims: brand.prohibited_claims.join(", "), approved_ctas: brand.approved_ctas.join(", "), locations: brand.locations.join(", ") });
  }, [brand]);
  const list = (s: string) => (s ?? "").split(",").map((x) => x.trim()).filter(Boolean);
  const save = async () => {
    const body = { name: f.name, industry: f.industry || null, description: f.description, website_url: f.website_url || null, colors: list(f.colors), fonts: list(f.fonts),
      target_customers: f.target_customers, products: (f.products ?? "").split("\n").map((s) => s.trim()).filter(Boolean).map((name) => ({ name, description: brand?.products.find((p) => p.name === name)?.description ?? "" })),
      voice: f.voice, competitor_references: list(f.competitor_references), prohibited_claims: list(f.prohibited_claims), approved_ctas: list(f.approved_ctas), locations: list(f.locations) };
    try { if (brand) await api.patch(`/brands/${brand.id}`, body); else await api.post("/brands", { ...body, is_default: true }); refetch(); m.ok("Brand saved. New drafts will use it."); } catch (e) { m.fail(e); }
  };
  const upload = async (file: File) => {
    if (!brand) return;
    const fd = new FormData(); fd.append("file", file); fd.append("purpose", "brand_logo");
    try { await api.upload(`/brands/${brand.id}/assets`, fd); refetch(); m.ok("Logo uploaded."); } catch (e) { m.fail(e); }
  };
  const field = (k: string, label: string, hint?: string, rows?: number) => (
    <Field key={k} label={label} hint={hint}>{rows ? <Textarea rows={rows} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} disabled={!canWrite} />
      : <Input value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} disabled={!canWrite} />}</Field>
  );
  return (
    <Panel title="Brand memory" description="Every agent reads this before generating anything.">
      {m.view}
      <div className="grid gap-4 md:grid-cols-2">
        {field("name", "Brand name")}{field("industry", "Industry")}
        {field("description", "Description", undefined, 3)}{field("target_customers", "Target customers", undefined, 3)}
        {field("voice", "Brand voice", "e.g. warm, witty, never pushy")}{field("website_url", "Website")}
        {field("colors", "Colours", "Hex values, comma separated")}{field("fonts", "Fonts", "Comma separated")}
        {field("products", "Products and services", "One per line", 4)}{field("approved_ctas", "Approved calls to action", "Comma separated")}
        {field("prohibited_claims", "Prohibited claims", "Drafts containing these can't be submitted")}{field("competitor_references", "Competitors", "Comma separated")}
        {field("locations", "Locations", "Comma separated")}
        <Field label="Logo">
          <div className="flex items-center gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {brand?.logo_url && <img src={brand.logo_url} alt="Logo" className="size-12 rounded border border-rule object-contain" />}
            {canWrite && brand && <input type="file" accept="image/png,image/jpeg,image/svg+xml,image/webp" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} className="text-[13px]" />}
          </div>
        </Field>
      </div>
      {canWrite && <Button variant="primary" className="mt-4" onClick={save}>Save brand</Button>}
    </Panel>
  );
}

function AuditLog() {
  const { data, error } = useApiQuery<{ id: string; action: string; actor: string | null; actor_type: string; resource_type: string | null; data: Record<string, unknown>; created_at: string; ip: string | null }[]>("/audit-logs");
  if (error) return <Notice tone="error">{errorMessage(error)}</Notice>;
  return (
    <Panel title="Audit log" description="Sensitive actions in this workspace: approvals, publishing, campaign changes, members, integrations and credits.">
      <Table head={["When", "Who", "Action", "Details"]}>
        {(data ?? []).map((e) => (
          <tr key={e.id}><td className="whitespace-nowrap text-[13px] text-muted">{new Date(e.created_at).toLocaleString("en-IN")}</td><td>{e.actor ?? e.actor_type}</td>
            <td className="font-mono text-[12px]">{e.action}</td><td className="max-w-md truncate text-xs text-muted">{Object.keys(e.data).length ? JSON.stringify(e.data) : e.resource_type ?? ""}</td></tr>
        ))}
      </Table>
    </Panel>
  );
}

function Settings() {
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "profile");
  const { data: ws } = useWorkspace();
  const canAudit = useCan("audit:read");
  return (
    <>
      <PageHeader title="Settings" />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "profile", label: "Profile & security" }, { value: "workspace", label: "Workspace" }, { value: "team", label: "Team" },
        { value: "brand", label: "Brand" }, ...(canAudit ? [{ value: "audit" as Tab, label: "Audit log" }] : [])]} />
      <div className="mt-5">
        {tab === "profile" && <Profile />}
        {tab === "workspace" && ws && <WorkspaceSettings key={ws.id} ws={ws} />}
        {tab === "team" && ws && <Team ws={ws} />}
        {tab === "brand" && <BrandSettings />}
        {tab === "audit" && <AuditLog />}
      </div>
    </>
  );
}

export default function SettingsPage() {
  return <Suspense><Settings /></Suspense>;
}
