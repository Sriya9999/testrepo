"use client";

import { formatMoney, formatNumber, type Kpi } from "@marketingos/api-client";
import { useState } from "react";
import { BarList, LineChart, SERIES_COLORS } from "@/components/charts";
import { RangePicker, useDateRange } from "@/components/filters";
import { Metric, MetricGrid, ProvenanceLegend } from "@/components/metric";
import { Button, Field, Input, Notice, PageHeader, Panel, ProvenanceMark, Select, StatusBadge, Table, Tabs, Textarea, Toggle } from "@/components/ui";
import { api, downloadFile } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useWorkspace } from "@/lib/hooks";

interface Overview { currency: string; kpis: Record<string, Kpi>; summary: string[]; contains_demo_data: boolean;
  series: { days: { date: string; organic_clicks: number | null; instagram_engagement: number | null }[]; paid: Record<string, { date: string; spend_minor: number; results: number }[]> };
  channels: { channel: string; spend_minor: number; clicks: number | null; conversions: number | null; cpa_minor: number | null; roas: number | null; revenue_minor: number | null; sources: string[] }[];
  top_campaigns: { name: string; spend_minor: number; results: number; cpa_minor: number | null }[]; top_posts: { id: string; caption: string; engagement: number }[] }
interface Answer { answer: string; facts: { label: string; value: string; previous: string; change_pct: number | null; kind: string; sources: string[] }[]; recommendations: { text?: string; kind: string }[] }
interface Report { id: string; name: string; format: string; status: string; schedule: string; generated_at: string | null; error: string | null; white_label: boolean }
interface ClientRow { workspace_id: string; name: string; underperforming: boolean; flags: string[]; kpis: Record<string, Kpi> }

const QUESTIONS = ["What caused my advertising costs to increase?", "Which content generated the highest engagement?", "Which campaigns generated the most leads?",
  "What is my organic traffic trend?", "Which clients are underperforming?", "Where should I allocate the next marketing budget?"];

export default function AnalyticsPage() {
  const { data: ws } = useWorkspace();
  const [range, setRange] = useDateRange(30);
  const [tab, setTab] = useState("overview");
  const [allClients, setAllClients] = useState(false);
  const { data } = useApiQuery<Overview>("/analytics/overview", { start: range.start, end: range.end, all_clients: allClients || undefined });
  const { data: roi } = useApiQuery<{ spend_minor: number; platform_reported_revenue_minor: number; roas: number | null; attribution_note: string }>("/analytics/roi", { start: range.start, end: range.end, all_clients: allClients || undefined });
  const { data: reports } = useApiQuery<Report[]>("/analytics/reports", undefined, { refetchInterval: (q) => ((q.state.data as Report[] | undefined)?.some((r) => r.status === "queued") ? 2000 : false) });
  const { data: clients } = useApiQuery<ClientRow[]>(ws?.kind === "agency" ? "/analytics/clients" : null, { start: range.start, end: range.end });
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const ask = useApiMutation((q: string) => api.post<Answer>("/analytics/ask", { question: q, start: range.start, end: range.end }), ["/billing"]);
  const [report, setReport] = useState({ name: "Monthly marketing report", format: "pdf", white_label: false, schedule: "once", recipients: "" });
  const [msg, setMsg] = useState("");
  const create = useApiMutation(() => api.post("/analytics/reports", { ...report, start: range.start, end: range.end, all_clients: allClients,
    recipients: report.recipients.split(",").map((s) => s.trim()).filter(Boolean) }), ["/analytics/reports"]);
  const cur = data?.currency ?? "INR";
  const paid = Object.entries(data?.series.paid ?? {});
  const dates = Array.from(new Set(paid.flatMap(([, rows]) => rows.map((r) => r.date)))).sort();

  return (
    <>
      <PageHeader title="Analytics" description="Every channel in one place, with each number labelled by where it comes from."
        actions={<>
          {ws?.kind === "agency" && <label className="flex items-center gap-2 text-[13px]"><Toggle checked={allClients} onChange={setAllClients} label="Include all clients" /> All clients</label>}
          <RangePicker value={range} onChange={setRange} />
          <Button onClick={() => downloadFile(`/analytics/export.csv?start=${range.start}&end=${range.end}`, `marketingos_${range.start}_${range.end}.csv`)}>Export CSV</Button>
        </>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "overview", label: "Overview" }, { value: "ask", label: "Ask about your data" }, { value: "reports", label: "Reports" },
        ...(ws?.kind === "agency" ? [{ value: "clients", label: "Clients" }] : [])]} />
      <div className="mt-5 space-y-5">
        {tab === "overview" && data && (
          <>
            {data.contains_demo_data && <Notice tone="warning">Includes demo data.</Notice>}
            <Panel title="Summary"><ul className="space-y-1 text-[14px]">{data.summary.map((s) => <li key={s}>{s}</li>)}</ul></Panel>
            <div className="space-y-2">
              <MetricGrid>
                {(["spend", "paid_traffic", "conversions", "cpl", "cpa", "roas", "ctr", "cpc", "impressions", "organic_traffic", "engagement", "geo_visibility"] as const).map((k) => (
                  <Metric key={k} label={{ spend: "Ad spend", paid_traffic: "Paid clicks", conversions: "Conversions", cpl: "Cost per lead", cpa: "CPA", roas: "ROAS", ctr: "CTR", cpc: "CPC",
                    impressions: "Ad impressions", organic_traffic: "Organic traffic", engagement: "Instagram engagement", geo_visibility: "GEO visibility" }[k]} kpi={data.kpis[k]} currency={cur} />
                ))}
              </MetricGrid>
              <ProvenanceLegend />
            </div>
            <div className="grid gap-5 lg:grid-cols-2">
              <Panel title="Ad spend trend">
                <LineChart title="Ad spend" labels={dates} format={(v) => formatMoney(v, cur)} series={paid.map(([p, rows]) => ({
                  key: p, label: p === "meta" ? "Meta Ads" : "Google Ads", color: SERIES_COLORS[p === "meta" ? 0 : 1], values: dates.map((d) => rows.find((r) => r.date === d)?.spend_minor ?? null) }))} />
              </Panel>
              <Panel title="Organic and social">
                <LineChart title="Organic clicks and Instagram engagement" labels={data.series.days.map((d) => d.date)} series={[
                  { key: "organic", label: "Organic clicks", color: SERIES_COLORS[1], values: data.series.days.map((d) => d.organic_clicks) },
                  { key: "ig", label: "Instagram engagement", color: SERIES_COLORS[2], values: data.series.days.map((d) => d.instagram_engagement) }]} />
              </Panel>
            </div>
            <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
              <Panel title="Channel comparison" description="Conversions are as reported by each platform.">
                <Table head={["Channel", "Spend", "Clicks", "Conversions", "CPA", "ROAS"]}>
                  {data.channels.map((c) => (
                    <tr key={c.channel}><td className="capitalize">{c.channel.replace(/_/g, " ")}</td><td className="tabular">{formatMoney(c.spend_minor, cur)}</td>
                      <td className="tabular">{formatNumber(c.clicks)}</td><td className="tabular">{formatNumber(c.conversions)}</td><td className="tabular">{formatMoney(c.cpa_minor, cur)}</td>
                      <td className="tabular">{c.roas != null ? `${c.roas.toFixed(2)}×` : "—"}</td></tr>
                  ))}
                </Table>
                {!data.channels.length && <p className="text-[13px] text-muted">No channel data in this period.</p>}
              </Panel>
              <Panel title="Marketing ROI">
                <p className="text-3xl font-bold tabular">{roi?.roas != null ? `${roi.roas.toFixed(2)}×` : "—"}</p>
                <p className="text-[13px] text-muted">{formatMoney(roi?.platform_reported_revenue_minor ?? null, cur)} reported revenue on {formatMoney(roi?.spend_minor ?? null, cur)} spend</p>
                <p className="mt-3 text-xs text-muted">{roi?.attribution_note}</p>
              </Panel>
            </div>
            <div className="grid gap-5 lg:grid-cols-2">
              <Panel title="Campaigns by results"><BarList items={data.top_campaigns.map((c) => ({ label: c.name, value: c.results, note: `${formatMoney(c.spend_minor, cur)} spent` }))} /></Panel>
              <Panel title="Posts by engagement"><BarList color={SERIES_COLORS[2]} items={data.top_posts.map((p) => ({ label: p.caption || "Untitled", value: p.engagement }))} /></Panel>
            </div>
          </>
        )}
        {tab === "ask" && (
          <div className="grid gap-5 lg:grid-cols-[1fr_300px]">
            <Panel title="Ask a question" description="Answers use only your measured data for the selected period. 2 credits per question.">
              <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); ask.mutate(question, { onSuccess: setAnswer }); }}>
                <Input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="What caused my advertising costs to increase?" />
                <Button variant="primary" loading={ask.isPending} disabled={question.length < 3}>Ask</Button>
              </form>
              {ask.error && <Notice tone="error" className="mt-3">{errorMessage(ask.error)}</Notice>}
              {answer && (
                <div className="mt-5 space-y-4">
                  <p className="text-[15px] leading-relaxed">{answer.answer}</p>
                  {answer.recommendations.length > 0 && (
                    <div className="rounded-md border border-dashed border-rule-strong p-3"><p className="mb-1 text-xs font-medium text-muted">Recommendation (AI suggestion, not a measurement)</p>
                      <ul className="list-disc pl-4 text-[13px]">{answer.recommendations.map((r, i) => <li key={i}>{r.text ?? JSON.stringify(r)}</li>)}</ul></div>
                  )}
                  <div><p className="mb-1.5 text-xs font-medium text-muted">Data used</p>
                    <Table head={["", "Metric", "This period", "Previous", "Source"]}>
                      {answer.facts.map((f) => <tr key={f.label}><td><ProvenanceMark kind={f.kind} /></td><td>{f.label}</td><td className="tabular">{f.value}</td><td className="tabular text-muted">{f.previous}</td><td className="text-xs text-muted">{f.sources.join(", ")}</td></tr>)}
                    </Table>
                  </div>
                </div>
              )}
            </Panel>
            <Panel title="Try asking">
              <ul className="space-y-1.5">{QUESTIONS.map((q) => <li key={q}><button className="text-left text-[13px] hover:underline" onClick={() => { setQuestion(q); ask.mutate(q, { onSuccess: setAnswer }); }}>{q}</button></li>)}</ul>
            </Panel>
          </div>
        )}
        {tab === "reports" && (
          <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
            <Panel title="New report">
              <div className="space-y-3">
                {msg && <Notice tone="error">{msg}</Notice>}
                <Field label="Name"><Input value={report.name} onChange={(e) => setReport({ ...report, name: e.target.value })} /></Field>
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Format"><Select value={report.format} onChange={(e) => setReport({ ...report, format: e.target.value })} options={[{ value: "pdf", label: "PDF" }, { value: "csv", label: "CSV" }]} /></Field>
                  <Field label="Repeat"><Select value={report.schedule} onChange={(e) => setReport({ ...report, schedule: e.target.value })} options={[{ value: "once", label: "Once" }, { value: "weekly", label: "Weekly" }, { value: "monthly", label: "Monthly" }]} /></Field>
                </div>
                <Field label="Email to" hint="Comma separated"><Textarea rows={2} value={report.recipients} onChange={(e) => setReport({ ...report, recipients: e.target.value })} /></Field>
                {ws?.kind !== "business" && <label className="flex items-center gap-2 text-[13px]"><Toggle checked={report.white_label} onChange={(v) => setReport({ ...report, white_label: v })} label="White label" /> Use agency branding</label>}
                <Button variant="primary" className="w-full" loading={create.isPending} onClick={() => create.mutate(undefined, { onError: (e) => setMsg(errorMessage(e)), onSuccess: () => setMsg("") })}>Generate report</Button>
              </div>
            </Panel>
            <Panel title="Reports">
              <Table head={["Report", "Format", "Repeats", "Status", ""]}>
                {(reports ?? []).map((r) => (
                  <tr key={r.id}><td>{r.name}{r.white_label && <span className="ml-1 text-xs text-muted">white label</span>}</td><td className="uppercase">{r.format}</td><td className="capitalize">{r.schedule}</td>
                    <td><StatusBadge status={r.status === "ready" ? "completed" : r.status} label={r.status === "ready" ? "Ready" : undefined} /></td>
                    <td>{r.status === "ready" && <button className="text-[13px] underline" onClick={() => downloadFile(`/analytics/reports/${r.id}/download`, `${r.name}.${r.format}`)}>Download</button>}</td></tr>
                ))}
              </Table>
              {!reports?.length && <p className="text-[13px] text-muted">No reports yet.</p>}
            </Panel>
          </div>
        )}
        {tab === "clients" && (
          <Panel title="Client performance" description="Flags compare this period with the one before.">
            <Table head={["Client", "Spend", "Conversions", "CPA", "Organic", "Flags"]}>
              {(clients ?? []).map((c) => (
                <tr key={c.workspace_id}><td className="font-medium">{c.name}</td><td className="tabular">{formatMoney(c.kpis.spend.value, cur)}</td><td className="tabular">{formatNumber(c.kpis.conversions.value)}</td>
                  <td className="tabular">{formatMoney(c.kpis.cpa.value, cur)}</td><td className="tabular">{formatNumber(c.kpis.organic_traffic.value)}</td>
                  <td>{c.underperforming ? <span className="text-[13px] text-danger">{c.flags.join("; ")}</span> : <span className="text-[13px] text-muted">On track</span>}</td></tr>
              ))}
            </Table>
          </Panel>
        )}
      </div>
    </>
  );
}
