"use client";

import { formatMoney } from "@marketingos/api-client";
import { BarList } from "@/components/charts";
import { Button, Notice, PageHeader, Panel, StatusBadge, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan } from "@/lib/hooks";

interface Plan { code: string; name: string; audience: string; price_minor: number | null; monthly_credits: number; limits: Record<string, number>; credit_policy: string }
interface Usage { subscription: { plan: Plan | null; status: string | null; current_period_end: string | null; provider: string | null }; usage: Record<string, number>; limits: Record<string, number>;
  credits: { balance: number; used_last_30_days: number; by_operation: { operation: string; credits: number }[] } }
interface Credits { balance: number; packs: { code: string; credits: number; price_minor: number }[]; costs: { operation: string; credits: number; description: string }[] }
type Pay = { status: string; mode: string; short_url?: string; order_id?: string; key_id?: string; message?: string };
const pretty = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export default function BillingPage() {
  const canManage = useCan("billing:manage");
  const { data: plans } = useApiQuery<Plan[]>("/billing/plans");
  const { data: usage } = useApiQuery<Usage>("/billing/usage");
  const { data: credits } = useApiQuery<Credits>("/billing/credits");
  const { data: txns } = useApiQuery<{ id: string; amount: number; balance_after: number; kind: string; description: string; created_at: string }[]>("/billing/transactions");
  const { data: invoices } = useApiQuery<{ id: string; number: string; amount_minor: number; currency: string; description: string; issued_at: string; status: string }[]>("/billing/invoices");
  const pay = useApiMutation((fn: () => Promise<Pay>) => fn(), ["/billing", "/workspaces"]);
  const handle = (r: Pay) => { if (r.short_url) window.location.href = r.short_url; };
  const current = usage?.subscription.plan?.code;

  return (
    <>
      <PageHeader title="Billing and credits" description="Your plan covers publishing, audits and seats. AI work uses credits, charged only when it succeeds. Ad spend is paid directly to Meta and Google." />
      {pay.error && <Notice tone="error" className="mb-4">{errorMessage(pay.error)}</Notice>}
      {pay.data?.message && <Notice tone="success" className="mb-4">{pay.data.message}</Notice>}
      <div className="grid gap-5 lg:grid-cols-3">
        <Panel title="Current plan">
          <p className="text-xl font-bold">{usage?.subscription.plan?.name ?? "—"}</p>
          <p className="text-[13px] text-muted"><StatusBadge status={usage?.subscription.status ?? "draft"} /> {usage?.subscription.current_period_end && `until ${new Date(usage.subscription.current_period_end).toLocaleDateString("en-IN")}`}</p>
          <p className="mt-2 text-xs text-muted">{usage?.subscription.plan?.credit_policy}</p>
        </Panel>
        <Panel title="Credit balance">
          <p className="text-3xl font-bold tabular">{credits?.balance ?? "—"}</p>
          <p className="text-[13px] text-muted">{usage?.credits.used_last_30_days ?? 0} used in the last 30 days</p>
          {canManage && <div className="mt-3 flex flex-wrap gap-2">{credits?.packs.map((p) => (
            <Button key={p.code} size="sm" loading={pay.isPending} onClick={() => pay.mutate(() => api.post<Pay>("/billing/credits/purchase", { pack: p.code }), { onSuccess: handle })}>
              +{p.credits} · {formatMoney(p.price_minor)}</Button>))}</div>}
        </Panel>
        <Panel title="Usage">
          <ul className="space-y-1.5 text-[13px]">
            {usage && Object.entries(usage.usage).map(([k, v]) => (
              <li key={k} className="flex justify-between"><span>{pretty(k)}</span><span className="tabular">{v}{usage.limits[k] !== undefined ? ` / ${usage.limits[k]}` : ""}</span></li>
            ))}
          </ul>
        </Panel>
      </div>
      <h2 className="mb-3 mt-8 text-lg font-bold tracking-tight">Plans</h2>
      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-5">
        {plans?.map((p) => (
          <div key={p.code} className={p.code === current ? "rounded-[var(--radius-panel)] border-2 border-ink bg-surface p-4" : "rounded-[var(--radius-panel)] border border-rule bg-surface p-4"}>
            <p className="font-semibold">{p.name}</p><p className="text-xs text-muted">{p.audience}</p>
            <p className="mt-3 text-xl font-bold tabular">{p.price_minor === null ? "Custom" : formatMoney(p.price_minor)}<span className="text-xs font-normal text-muted">{p.price_minor !== null && " /month"}</span></p>
            <p className="text-[13px]">{p.monthly_credits ? `${p.monthly_credits.toLocaleString("en-IN")} credits a month` : "Credits to suit"}</p>
            <ul className="mt-2 space-y-0.5 text-xs text-muted">{Object.entries(p.limits).slice(0, 5).map(([k, v]) => <li key={k}>{v} {pretty(k).toLowerCase()}</li>)}</ul>
            {canManage && p.code !== current && <Button size="sm" className="mt-3 w-full" variant={p.price_minor === null ? "secondary" : "primary"} loading={pay.isPending}
              onClick={() => pay.mutate(() => api.post<Pay>("/billing/subscribe", { plan_code: p.code }), { onSuccess: handle })}>{p.price_minor === null ? "Contact us" : "Choose"}</Button>}
            {p.code === current && <p className="mt-3 text-center text-xs font-semibold">Your plan</p>}
          </div>
        ))}
      </div>
      <div className="mt-8 grid gap-5 lg:grid-cols-2">
        <Panel title="Credits by activity (30 days)"><BarList items={(usage?.credits.by_operation ?? []).map((o) => ({ label: pretty(o.operation), value: o.credits }))} /></Panel>
        <Panel title="Price list" description="Credits per operation. You see the estimate before anything runs.">
          <Table head={["Activity", "Credits"]}>{credits?.costs.map((c) => <tr key={c.operation}><td>{c.description}</td><td className="tabular">{c.credits}</td></tr>)}</Table>
        </Panel>
        <Panel title="Credit transactions">
          <Table head={["Date", "Description", "Change", "Balance"]}>
            {(txns ?? []).slice(0, 30).map((t) => <tr key={t.id}><td className="whitespace-nowrap text-[13px] text-muted">{new Date(t.created_at).toLocaleDateString("en-IN")}</td><td>{t.description || pretty(t.kind)}</td>
              <td className={t.amount < 0 ? "tabular text-danger" : "tabular text-leaf"}>{t.amount > 0 ? "+" : ""}{t.amount}</td><td className="tabular">{t.balance_after}</td></tr>)}
          </Table>
        </Panel>
        <Panel title="Invoices">
          <Table head={["Number", "Date", "Description", "Amount"]}>
            {(invoices ?? []).map((i) => <tr key={i.id}><td>{i.number}</td><td className="text-[13px] text-muted">{new Date(i.issued_at).toLocaleDateString("en-IN")}</td><td>{i.description}</td><td className="tabular">{formatMoney(i.amount_minor, i.currency, 2)}</td></tr>)}
          </Table>
          {!invoices?.length && <p className="text-[13px] text-muted">No invoices yet.</p>}
        </Panel>
      </div>
    </>
  );
}
