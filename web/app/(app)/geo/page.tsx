"use client";

import Link from "next/link";
import { BarList, LineChart, ScoreRing, SERIES_COLORS } from "@/components/charts";
import { GeoProjectPicker, useGeoProjects } from "@/components/search-pickers";
import { Empty, LinkButton, Notice, PageHeader, Panel, Spinner, Table } from "@/components/ui";
import { useApiQuery } from "@/lib/hooks";

interface Vis { results: number; geo_score: number | null; mention_rate?: number; citation_rate?: number; share_of_voice?: number; avg_position?: number | null; avg_sentiment?: number | null;
  prompt_coverage?: number; prompts?: number; top_cited_domains?: { domain: string; count: number }[] }
interface Visibility { overall: Vis; by_provider: Record<string, Vis>; history: { date: string; geo_score: number | null; mention_rate?: number }[]; score_note: string }
const pct = (v?: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const PROVIDERS: Record<string, string> = { openai_search: "ChatGPT search", perplexity: "Perplexity", "manual:google_ai_overview": "Google AI Overviews (imported)", "manual:copilot": "Copilot (imported)", "manual:chatgpt": "ChatGPT (imported)" };

export default function GeoPage() {
  const { current, projects, isLoading } = useGeoProjects();
  const { data: v } = useApiQuery<Visibility>(current ? "/geo/visibility" : null, { project_id: current?.id, days: 30 });
  const { data: comp } = useApiQuery<{ rows: { name: string; is_brand: boolean; mention_rate: number | null; share_of_voice: number | null }[] }>(current ? "/geo/competitors" : null, { project_id: current?.id });
  const { data: recs } = useApiQuery<{ recommendations: { type: string; title: string; reason: string; action: string; priority: string; content_brief?: Record<string, string> }[]; note: string | null }>(current ? "/geo/recommendations" : null, { project_id: current?.id });
  const o = v?.overall;
  return (
    <>
      <PageHeader title="AI search visibility" description="How often answer engines mention and cite your brand when people ask the questions you track." actions={<GeoProjectPicker />} />
      {isLoading && <Spinner />}
      {projects && !projects.length && <Empty title="Start tracking AI answers" body="Create a project with your brand and competitors, then add the questions your customers ask." />}
      {current && v && (
        <div className="space-y-5">
          {!o?.results && <Notice tone="info">No answers collected in the last 30 days. <Link href="/geo/prompts" className="underline">Run monitoring or import answers</Link>.</Notice>}
          <div className="grid gap-5 lg:grid-cols-[260px_1fr]">
            <Panel>
              <div className="flex flex-col items-center gap-2 p-5 text-center">
                <ScoreRing value={o?.geo_score ?? null} label="GEO visibility score" size={120} />
                <p className="text-xs text-muted">{v.score_note}</p>
              </div>
            </Panel>
            <div className="grid grid-cols-2 overflow-hidden rounded-[var(--radius-panel)] border border-rule bg-surface sm:grid-cols-3 [&>div]:border-b [&>div]:border-r [&>div]:border-rule">
              {[["Brand mentioned", pct(o?.mention_rate), "of answers"], ["Site cited", pct(o?.citation_rate), "of answers"], ["Share of voice", pct(o?.share_of_voice), "vs competitors"],
                ["Prompt coverage", pct(o?.prompt_coverage), `of ${o?.prompts ?? 0} questions`], ["Average position", o?.avg_position?.toFixed(1) ?? "—", "1 = named first"],
                ["Sentiment", o?.avg_sentiment == null ? "—" : o.avg_sentiment > 0.2 ? "Positive" : o.avg_sentiment < -0.2 ? "Negative" : "Neutral", "around mentions"]].map(([k, val, sub]) => (
                <div key={k} className="px-4 py-3.5"><p className="text-[13px] text-muted">{k}</p><p className="text-[22px] font-bold tabular">{val}</p><p className="text-xs text-faint">{sub}</p></div>
              ))}
            </div>
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <Panel title="Mention rate over time">
              <LineChart title="Mention rate" labels={v.history.map((h) => h.date)} format={(x) => `${Math.round(x * 100)}%`}
                series={[{ key: "mention", label: "Mention rate", color: SERIES_COLORS[0], values: v.history.map((h) => h.mention_rate ?? null) }]} />
            </Panel>
            <Panel title="Share of voice">
              <BarList items={(comp?.rows ?? []).map((r) => ({ label: r.is_brand ? `${r.name} (you)` : r.name, value: Math.round((r.share_of_voice ?? 0) * 100) }))} format={(x) => `${x}%`} />
            </Panel>
          </div>
          <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr]">
            <Panel title="Recommendations">
              {recs?.recommendations.length ? (
                <ul className="space-y-3">
                  {recs.recommendations.map((r) => (
                    <li key={r.title} className="text-[13px]">
                      <p className="font-medium">{r.title}</p><p className="text-ink-2">{r.reason}</p><p className="text-muted">{r.action}</p>
                      {r.content_brief && <Link className="text-xs underline" href={`/content-studio?question=${encodeURIComponent(r.content_brief.question ?? "")}`}>Draft an answer article</Link>}
                    </li>
                  ))}
                </ul>
              ) : <p className="text-[13px] text-muted">{recs?.note ?? "No recommendations yet."}</p>}
            </Panel>
            <div className="space-y-5">
              <Panel title="By answer engine">
                <Table head={["Engine", "Answers", "Mentioned", "Cited"]}>
                  {Object.entries(v.by_provider).map(([p, s]) => (
                    <tr key={p}><td>{PROVIDERS[p] ?? p}</td><td className="tabular">{s.results}</td><td className="tabular">{pct(s.mention_rate)}</td><td className="tabular">{pct(s.citation_rate)}</td></tr>
                  ))}
                </Table>
              </Panel>
              <Panel title="Most cited sources">
                <BarList items={(o?.top_cited_domains ?? []).map((d) => ({ label: d.domain, value: d.count }))} color={SERIES_COLORS[2]} />
              </Panel>
            </div>
          </div>
          <LinkButton href="/geo/prompts">Manage prompts and results</LinkButton>
        </div>
      )}
    </>
  );
}
