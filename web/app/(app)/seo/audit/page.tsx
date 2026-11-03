"use client";

import { useState } from "react";
import { useWebsites, WebsitePicker } from "@/components/search-pickers";
import { Button, cn, Empty, Field, Input, Notice, PageHeader, Panel, Select, StatusBadge, Table, Tabs, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan } from "@/lib/hooks";

interface Audit { id: string; status: string; score: number | null; pages_crawled: number; progress: number; created_at: string; finished_at: string | null; error: string | null;
  competitor_id: string | null; summary: Record<string, any>; config: Record<string, any> }
interface Issue { id: string; code: string; category: string; severity: string; message: string; page_url: string | null; details: Record<string, any> }
interface AuditDetail extends Audit { issues: Issue[]; recommendations: { title: string; reason: string; steps: string[]; priority: string; estimated_impact: string; affected_pages: number; examples: string[] }[];
  pages: { url: string; status_code: number | null; title: string | null; word_count: number | null; elapsed_ms: number | null }[] }

const SEV_CLS: Record<string, string> = { critical: "bg-danger text-white", high: "bg-danger-wash text-danger", medium: "bg-marigold-wash text-marigold-deep", low: "bg-sunk text-ink-2" };

export default function AuditPage() {
  const { current } = useWebsites();
  const canWrite = useCan("seo:write");
  const [maxPages, setMaxPages] = useState(50);
  const [pagespeed, setPagespeed] = useState(true);
  const [target, setTarget] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [severity, setSeverity] = useState("");
  const [tab, setTab] = useState("recommendations");
  const [error, setError] = useState("");
  const { data: audits } = useApiQuery<Audit[]>(current ? "/seo/audits" : null, { website_id: current?.id }, {
    refetchInterval: (q) => ((q.state.data as Audit[] | undefined)?.some((a) => ["queued", "running"].includes(a.status)) ? 2000 : false),
  });
  const own = audits?.filter((a) => !a.competitor_id) ?? [];
  const auditId = selected ?? own.find((a) => a.status === "completed")?.id ?? own[0]?.id;
  const { data: audit } = useApiQuery<AuditDetail>(auditId ? `/seo/audits/${auditId}` : null, { severity: severity || undefined }, {
    refetchInterval: (q) => (["queued", "running"].includes((q.state.data as Audit | undefined)?.status ?? "") ? 2000 : false),
  });
  const start = useApiMutation(() => api.post<{ audit_id: string }>("/seo/audits", { website_id: current!.id, max_pages: maxPages, include_pagespeed: pagespeed, competitor_id: target || null }), ["/seo"]);

  return (
    <>
      <PageHeader title="Website audit" description="A crawl of your site that respects robots.txt, checks technical, on-page, content and speed issues, and ranks the fixes." actions={<WebsitePicker />} />
      {!current ? <Empty title="Add a website first" /> : (
        <div className="space-y-5">
          <Panel title="Run an audit">
            {error && <Notice tone="error" className="mb-3">{error}</Notice>}
            <div className="flex flex-wrap items-end gap-4">
              <Field label="Site"><Select value={target} onChange={(e) => setTarget(e.target.value)} className="w-56"
                options={[{ value: "", label: current.domain }, ...current.competitors.filter((c) => c.domain).map((c) => ({ value: c.id, label: `Competitor: ${c.domain}` }))]} /></Field>
              <Field label="Pages to crawl"><Input type="number" min={1} max={500} value={maxPages} onChange={(e) => setMaxPages(Number(e.target.value))} className="w-28" /></Field>
              <label className="flex items-center gap-2 pb-2 text-[13px]"><Toggle checked={pagespeed} onChange={setPagespeed} label="Include page speed" /> Page speed (Core Web Vitals)</label>
              <Button variant="primary" disabled={!canWrite} loading={start.isPending} onClick={() => start.mutate(undefined, { onSuccess: (r) => { setSelected(r.audit_id); setError(""); }, onError: (e) => setError(errorMessage(e)) })}>Start audit</Button>
            </div>
          </Panel>
          {audit && (
            <Panel title={<span className="flex items-center gap-2">{audit.config.domain} <StatusBadge status={audit.status} /></span>}
              description={audit.finished_at ? `Finished ${new Date(audit.finished_at).toLocaleString("en-IN")} · ${audit.pages_crawled} pages` : `${audit.pages_crawled} pages so far`}
              actions={own.length > 1 && <Select aria-label="Audit history" className="w-52" value={auditId ?? ""} onChange={(e) => setSelected(e.target.value)}
                options={(audits ?? []).map((a) => ({ value: a.id, label: `${new Date(a.created_at).toLocaleDateString("en-IN")} · ${a.competitor_id ? "competitor" : "own"} · ${a.score ?? a.status}` }))} />}>
              {["queued", "running"].includes(audit.status) && (
                <div className="mb-4"><div className="h-2 rounded-full bg-sunk"><div className="h-2 rounded-full bg-series-1 transition-all" style={{ width: `${audit.progress}%` }} /></div>
                  <p className="mt-1 text-xs text-muted">Crawling… {audit.progress}%</p></div>
              )}
              {audit.error && <Notice tone="error">{audit.error}</Notice>}
              {audit.status === "completed" && (
                <>
                  <div className="mb-4 flex flex-wrap gap-6 text-[13px]">
                    <p><span className="text-3xl font-bold tabular">{audit.score}</span><span className="text-muted">/100 health</span></p>
                    <p>robots.txt: <b>{audit.summary.robots?.status === 200 ? "found" : "missing"}</b></p>
                    <p>Sitemap: <b>{audit.summary.sitemap?.status === 200 ? `${audit.summary.sitemap.urls} URLs` : "missing"}</b></p>
                    <p>HTTPS: <b>{audit.summary.https ? "yes" : "no"}</b></p>
                    {audit.summary.performance?.performance_score != null && <p>Mobile speed: <b>{audit.summary.performance.performance_score}/100</b></p>}
                  </div>
                  <Tabs value={tab} onChange={setTab} tabs={[{ value: "recommendations", label: "Recommended fixes", count: audit.recommendations.length },
                    { value: "issues", label: "All issues", count: audit.issues.length }, { value: "pages", label: "Pages", count: audit.pages.length }]} />
                  <div className="mt-4">
                    {tab === "recommendations" && (
                      <ol className="space-y-3">
                        {audit.recommendations.map((r, i) => (
                          <li key={r.title} className="rounded-md border border-rule p-3">
                            <div className="flex flex-wrap items-center gap-2"><span className="text-xs font-semibold tabular text-muted">{i + 1}</span><span className="font-semibold">{r.title}</span>
                              <span className={cn("rounded px-1.5 text-[11px] font-medium", SEV_CLS[r.priority])}>{r.priority}</span>
                              <span className="text-xs text-muted">{r.estimated_impact} impact · {r.affected_pages} page{r.affected_pages === 1 ? "" : "s"}</span></div>
                            <p className="mt-1 text-[13px] text-ink-2">{r.reason}</p>
                            <ol className="mt-1 list-decimal pl-5 text-[13px]">{r.steps.map((s) => <li key={s}>{s}</li>)}</ol>
                            {r.examples.length > 0 && <p className="mt-1 truncate text-xs text-muted">e.g. {r.examples.slice(0, 2).join(", ")}</p>}
                          </li>
                        ))}
                      </ol>
                    )}
                    {tab === "issues" && (
                      <>
                        <div className="mb-3 flex gap-2">{["", "critical", "high", "medium", "low"].map((s) => (
                          <button key={s} onClick={() => setSeverity(s)} className={cn("rounded-full border px-2.5 py-0.5 text-xs", severity === s ? "border-ink bg-ink text-white" : "border-rule-strong")}>{s || "All"}</button>
                        ))}</div>
                        <Table head={["Severity", "Issue", "Category", "Page"]}>
                          {audit.issues.map((i) => (
                            <tr key={i.id}><td><span className={cn("rounded px-1.5 text-[11px] font-medium", SEV_CLS[i.severity])}>{i.severity}</span></td><td>{i.message}</td>
                              <td className="capitalize">{i.category.replace("_", "-")}</td><td className="max-w-xs truncate text-xs text-muted">{i.page_url ?? "site-wide"}</td></tr>
                          ))}
                        </Table>
                      </>
                    )}
                    {tab === "pages" && (
                      <Table head={["URL", "Status", "Title", "Words", "Response"]}>
                        {audit.pages.map((p) => (
                          <tr key={p.url}><td className="max-w-xs truncate">{p.url}</td><td className={cn("tabular", (p.status_code ?? 0) >= 400 && "text-danger")}>{p.status_code ?? "error"}</td>
                            <td className="max-w-xs truncate">{p.title ?? "—"}</td><td className="tabular">{p.word_count ?? "—"}</td><td className="tabular">{p.elapsed_ms ? `${p.elapsed_ms} ms` : "—"}</td></tr>
                        ))}
                      </Table>
                    )}
                  </div>
                </>
              )}
            </Panel>
          )}
        </div>
      )}
    </>
  );
}
