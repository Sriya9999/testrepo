"use client";

import { formatMoney, formatNumber, type Approval, type Kpi } from "@marketingos/api-client";
import Link from "next/link";
import { useState } from "react";
import { ApprovalItem } from "@/components/approval";
import { LineChart, SERIES_COLORS } from "@/components/charts";
import { RangePicker, useDateRange } from "@/components/filters";
import { Metric, MetricGrid, ProvenanceLegend } from "@/components/metric";
import { Empty, LinkButton, Notice, PageHeader, Panel, Select, Spinner, StatusBadge, Table, Tag } from "@/components/ui";
import { useApiQuery, useWorkspace } from "@/lib/hooks";
import { useAuth } from "@/lib/store";

interface Dashboard {
  currency: string;
  kpis: Record<string, Kpi>;
  summary: string[];
  contains_demo_data: boolean;
  series: { days: { date: string; organic_clicks: number | null; organic_sessions: number | null; instagram_engagement: number | null }[];
    paid: Record<string, { date: string; spend_minor: number; clicks: number }[]> };
  pending_approvals: Approval[];
  pending_approvals_count: number;
  recent_campaigns: { id: string; name: string; platform: string; status: string; metrics: Record<string, number | null> | null }[];
  recommendations: { title: string; action: string; priority: string; campaign_id: string }[];
  upcoming_posts: { id: string; caption: string; scheduled_at: string | null; status: string }[];
  data_freshness: { provider: string; name: string; mode: string; status: string; last_sync_at: string | null; error: string | null }[];
  credits: { balance: number };
}

const KPI_ORDER: [string, string, string?][] = [
  ["organic_traffic", "Organic traffic", "/seo"], ["paid_traffic", "Paid clicks", "/advertising/meta"], ["seo_score", "SEO score", "/seo"],
  ["geo_visibility", "GEO visibility", "/geo"], ["impressions", "Ad impressions", "/advertising/meta"], ["engagement", "Engagement", "/social/calendar"],
  ["spend", "Ad spend", "/analytics"], ["ctr", "CTR", "/analytics"], ["cpc", "CPC", "/analytics"], ["cpl", "Cost per lead", "/analytics"],
  ["cpa", "CPA", "/analytics"], ["roas", "ROAS", "/analytics"],
];

export default function DashboardPage() {
  const user = useAuth((s) => s.user);
  const { data: ws } = useWorkspace();
  const [range, setRange] = useDateRange(30);
  const [platform, setPlatform] = useState("");
  const [scope, setScope] = useState<"workspace" | "all_clients">("workspace");
  const { data, isLoading, error } = useApiQuery<Dashboard>("/dashboard", {
    start: range.start, end: range.end, platform, all_clients: scope === "all_clients" ? true : undefined,
  });

  const currency = data?.currency ?? "INR";
  const days = data?.series.days ?? [];
  const paidDates = Array.from(new Set(Object.values(data?.series.paid ?? {}).flat().map((d) => d.date))).sort();
  const paidSeries = Object.entries(data?.series.paid ?? {}).map(([p, rows], i) => ({
    key: p, label: p === "meta" ? "Meta Ads" : "Google Ads", color: SERIES_COLORS[p === "meta" ? 0 : 1] ?? SERIES_COLORS[i],
    values: paidDates.map((d) => rows.find((r) => r.date === d)?.spend_minor ?? null),
  }));

  return (
    <>
      <PageHeader
        title={`Hello${user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}`}
        description={ws ? `${ws.name}: the last ${range.days} days, compared with the ${range.days} days before.` : undefined}
        actions={
          <>
            {ws?.kind === "agency" && (
              <Select aria-label="Scope" value={scope} onChange={(e) => setScope(e.target.value as typeof scope)} className="w-40"
                options={[{ value: "workspace", label: "Agency only" }, { value: "all_clients", label: "All my clients" }]} />
            )}
            <Select aria-label="Platform" value={platform} onChange={(e) => setPlatform(e.target.value)} className="w-40"
              options={[{ value: "", label: "All platforms" }, { value: "meta", label: "Meta" }, { value: "google", label: "Google" }]} />
            <RangePicker value={range} onChange={setRange} />
          </>
        }
      />
      {error && <Notice tone="error">{String(error)}</Notice>}
      {isLoading && <Spinner />}
      {data && (
        <div className="space-y-6">
          {data.contains_demo_data && <Notice tone="warning">This workspace contains demo data. Figures marked as demo are samples, not your results.</Notice>}

          <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
            <section aria-labelledby="signoff">
              <div className="mb-3 flex items-baseline justify-between gap-3">
                <h2 id="signoff" className="text-lg font-bold tracking-tight">
                  Waiting for your sign-off
                  {data.pending_approvals_count > 0 && <span className="ml-2 rounded-full bg-marigold px-2 text-sm tabular">{data.pending_approvals_count}</span>}
                </h2>
                {data.pending_approvals_count > 0 && <Link href="/approvals" className="text-[13px] font-medium underline-offset-2 hover:underline">Open approvals</Link>}
              </div>
              {data.pending_approvals.length ? (
                <div className="space-y-3">
                  {data.pending_approvals.slice(0, 3).map((a) => <ApprovalItem key={a.id} a={a} compact />)}
                </div>
              ) : (
                <Empty title="Nothing is waiting for you"
                  body="Ask the assistant to plan a month of content or a campaign. Everything it prepares lands here before it goes live."
                  action={<LinkButton href="/assistant" variant="primary">Plan with the assistant</LinkButton>} />
              )}
            </section>
            <Panel title="This period">
              <ul className="space-y-2 text-[14px] leading-relaxed">
                {data.summary.map((s) => <li key={s}>{s}</li>)}
              </ul>
              <div className="mt-4 border-t border-rule pt-3">
                <p className="mb-2 text-xs font-medium text-muted">Data sources</p>
                {data.data_freshness.length ? (
                  <ul className="space-y-1.5 text-[13px]">
                    {data.data_freshness.map((d) => (
                      <li key={d.provider + d.name} className="flex items-center justify-between gap-2">
                        <span className="truncate">{d.name} {d.mode === "sandbox" && <Tag tone="sandbox">sandbox</Tag>}</span>
                        <span className="shrink-0 text-xs text-muted">
                          {d.error ? <StatusBadge status="error" label="Sync error" /> : d.last_sync_at ? `synced ${new Date(d.last_sync_at).toLocaleDateString("en-IN")}` : "not synced yet"}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="text-[13px] text-muted">No integrations yet. <Link href="/integrations" className="underline">Connect one</Link> to see real numbers.</p>}
              </div>
            </Panel>
          </div>

          <div className="space-y-2">
            <MetricGrid>
              {KPI_ORDER.map(([key, label, href]) => <Metric key={key} label={label} kpi={data.kpis[key]} currency={currency} href={href} />)}
            </MetricGrid>
            <ProvenanceLegend />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="Ad spend by platform">
              <LineChart title="Daily ad spend by platform" labels={paidDates} series={paidSeries} format={(v) => formatMoney(v, currency)} />
            </Panel>
            <Panel title="Organic search">
              <LineChart title="Daily organic clicks" labels={days.map((d) => d.date)}
                series={[{ key: "clicks", label: "Organic clicks", color: SERIES_COLORS[1], values: days.map((d) => d.organic_clicks) }]} />
            </Panel>
          </div>

          <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
            <Panel title="Recent campaigns" actions={<LinkButton href="/advertising/meta">All campaigns</LinkButton>}>
              {data.recent_campaigns.length ? (
                <Table head={["Campaign", "Status", "Spend", "Results", "CPA"]}>
                  {data.recent_campaigns.map((c) => (
                    <tr key={c.id}>
                      <td><Link className="font-medium hover:underline" href={`/advertising/${c.platform}?campaign=${c.id}`}>{c.name}</Link>
                        <span className="block text-xs text-muted">{c.platform === "meta" ? "Meta" : "Google"}</span></td>
                      <td><StatusBadge status={c.status} /></td>
                      <td className="tabular">{formatMoney(c.metrics?.spend_minor ?? null, currency)}</td>
                      <td className="tabular">{formatNumber(c.metrics?.results ?? null)}</td>
                      <td className="tabular">{formatMoney(c.metrics?.cpa_minor ?? null, currency)}</td>
                    </tr>
                  ))}
                </Table>
              ) : <p className="text-[13px] text-muted">No campaigns yet.</p>}
            </Panel>
            <Panel title="Recommendations" description="From your synced ad performance.">
              {data.recommendations.length ? (
                <ul className="space-y-3">
                  {data.recommendations.map((r) => (
                    <li key={r.title} className="text-[13px]">
                      <p className="font-medium">{r.title}</p>
                      <p className="text-muted">{r.action}</p>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-[13px] text-muted">Recommendations appear once campaigns have run and synced performance data.</p>}
              {data.upcoming_posts.length > 0 && (
                <div className="mt-4 border-t border-rule pt-3">
                  <p className="mb-2 text-xs font-medium text-muted">Coming up on Instagram</p>
                  <ul className="space-y-1.5 text-[13px]">
                    {data.upcoming_posts.map((p) => (
                      <li key={p.id} className="flex justify-between gap-3">
                        <span className="truncate">{p.caption || "Untitled post"}</span>
                        <span className="shrink-0 text-xs text-muted">{p.scheduled_at ? new Date(p.scheduled_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "—"}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </Panel>
          </div>
        </div>
      )}
    </>
  );
}
