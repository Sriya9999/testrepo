"use client";

import Link from "next/link";
import { LineChart, ScoreRing, SERIES_COLORS } from "@/components/charts";
import { useWebsites, WebsitePicker } from "@/components/search-pickers";
import { Empty, LinkButton, PageHeader, Panel, Spinner, Table } from "@/components/ui";
import { useApiQuery } from "@/lib/hooks";

interface Overview {
  score: number | null; score_note: string; issues: Record<string, number>; history: { date: string; score: number }[];
  organic_traffic: { date: string; clicks: number | null; impressions: number | null; source: string }[];
  top_keywords: { text: string; position: number; position_change: number | null }[]; keywords_tracked: number; latest_audit_id: string | null;
}
interface Rec { title: string; reason: string; estimated_impact: string; priority: string; steps: string[]; affected_pages: number; category: string }
interface Competitors { own: Record<string, any> | null; competitors: { id: string; name: string; domain: string; latest_audit: Record<string, any> | null }[] }

export default function SeoPage() {
  const { current, websites, isLoading } = useWebsites();
  const id = current?.id;
  const { data: ov } = useApiQuery<Overview>(id ? "/seo/overview" : null, { website_id: id });
  const { data: recs } = useApiQuery<{ recommendations: Rec[]; note: string | null }>(id ? "/seo/recommendations" : null, { website_id: id });
  const { data: comp } = useApiQuery<Competitors>(id ? "/seo/competitors" : null, { website_id: id });

  return (
    <>
      <PageHeader title="SEO" description="Technical health, rankings and content opportunities for your websites." actions={<WebsitePicker />} />
      {isLoading && <Spinner />}
      {websites && !websites.length && <Empty title="Add your website" body="We'll crawl it, find technical and on-page issues and track your keywords." />}
      {current && ov && (
        <div className="space-y-5">
          <div className="grid gap-5 lg:grid-cols-[260px_1fr]">
            <Panel>
              <div className="flex flex-col items-center gap-3 p-5 text-center">
                <ScoreRing value={ov.score} label="SEO health score" size={120} />
                <p className="text-xs text-muted">{ov.score_note}</p>
                <div className="flex gap-3 text-[13px]">
                  {(["critical", "high", "medium", "low"] as const).map((s) => <span key={s}><b className="tabular">{ov.issues[s] ?? 0}</b> <span className="text-muted">{s}</span></span>)}
                </div>
                <LinkButton href="/seo/audit" variant="primary">{ov.latest_audit_id ? "View audit" : "Run first audit"}</LinkButton>
              </div>
            </Panel>
            <Panel title="Organic search" description={ov.organic_traffic.length ? `Source: ${[...new Set(ov.organic_traffic.map((t) => t.source))].join(", ")}` : undefined}>
              {ov.organic_traffic.length ? (
                <LineChart title="Organic clicks" labels={ov.organic_traffic.map((d) => d.date)}
                  series={[{ key: "clicks", label: "Clicks", color: SERIES_COLORS[1], values: ov.organic_traffic.map((d) => d.clicks) }]} />
              ) : <p className="py-8 text-center text-[13px] text-muted">Connect Search Console in <Link href="/integrations" className="underline">Integrations</Link> and set the property on this website to see clicks and positions.</p>}
            </Panel>
          </div>
          <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
            <Panel title="What to fix first" description="Each recommendation explains why it matters and how to do it.">
              {recs?.recommendations.length ? (
                <ul className="divide-y divide-rule">
                  {recs.recommendations.slice(0, 8).map((r) => (
                    <li key={r.title} className="py-3 first:pt-0">
                      <details>
                        <summary className="cursor-pointer list-none">
                          <span className="font-medium">{r.title}</span>
                          <span className="ml-2 text-xs text-muted">{r.priority} priority · {r.estimated_impact} impact{r.affected_pages ? ` · ${r.affected_pages} pages` : ""}</span>
                        </summary>
                        <p className="mt-2 text-[13px] text-ink-2">{r.reason}</p>
                        <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-[13px]">{r.steps.map((s) => <li key={s}>{s}</li>)}</ol>
                      </details>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-[13px] text-muted">{recs?.note ?? "No recommendations yet."}</p>}
            </Panel>
            <div className="space-y-5">
              <Panel title="Top rankings" actions={<LinkButton href="/seo/keywords">Keywords</LinkButton>}>
                {ov.top_keywords.length ? (
                  <Table head={["Keyword", "Position", "Change"]}>
                    {ov.top_keywords.map((k) => (
                      <tr key={k.text}><td>{k.text}</td><td className="tabular">{k.position.toFixed(1)}</td>
                        <td className={k.position_change && k.position_change > 0 ? "text-leaf" : k.position_change ? "text-danger" : "text-muted"}>{k.position_change ? `${k.position_change > 0 ? "▲" : "▼"} ${Math.abs(k.position_change)}` : "—"}</td></tr>
                    ))}
                  </Table>
                ) : <p className="text-[13px] text-muted">{ov.keywords_tracked ? "Positions appear after Search Console syncs." : "Track keywords to see rankings."}</p>}
              </Panel>
              <Panel title="Competitors">
                <Table head={["Site", "Score", "Pages", "Structured data"]}>
                  {comp?.own && <tr><td className="font-medium">{current.domain}</td><td className="tabular">{comp.own.score}</td><td className="tabular">{comp.own.pages_crawled}</td><td>{comp.own.structured_data?.join(", ") || "none"}</td></tr>}
                  {comp?.competitors.map((c) => (
                    <tr key={c.id}><td>{c.domain ?? c.name}</td><td className="tabular">{c.latest_audit?.score ?? "—"}</td><td className="tabular">{c.latest_audit?.pages_crawled ?? "—"}</td>
                      <td>{c.latest_audit ? c.latest_audit.structured_data?.join(", ") || "none" : <Link className="underline" href="/seo/audit">Audit it</Link>}</td></tr>
                  ))}
                </Table>
              </Panel>
            </div>
          </div>
          {ov.history.length > 1 && (
            <Panel title="Score history">
              <LineChart title="SEO score over time" labels={ov.history.map((h) => h.date.slice(0, 10))}
                series={[{ key: "score", label: "Score", color: SERIES_COLORS[0], values: ov.history.map((h) => h.score) }]} />
            </Panel>
          )}
        </div>
      )}
    </>
  );
}
