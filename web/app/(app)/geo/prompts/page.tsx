"use client";

import { useState } from "react";
import { GeoProjectPicker, useGeoProjects } from "@/components/search-pickers";
import { Button, cn, Drawer, Empty, Field, Input, Notice, PageHeader, Panel, Select, Table, Tag, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan, useJob } from "@/lib/hooks";

interface Prompt { id: string; text: string; category: string; location: string | null; active: boolean; source: string; latest: Record<string, { mentioned: boolean; cited: boolean; position: number | null }> }
interface Result { id: string; prompt: string; provider: string; status: string; response_text: string; citations: { url: string; title: string | null }[]; brand_mentioned: boolean; brand_cited: boolean;
  brand_position: number | null; competitor_mentions: Record<string, number>; sentiment: number | null; error: string | null; observed_at: string }
interface Provider { id: string; name: string; mode: string; available: boolean; note?: string }
const CATS = ["industry", "local", "comparison", "purchase", "informational"];

export default function GeoPromptsPage() {
  const { current } = useGeoProjects();
  const canWrite = useCan("geo:write");
  const [cat, setCat] = useState("");
  const [text, setText] = useState("");
  const [newCat, setNewCat] = useState("informational");
  const [location, setLocation] = useState("");
  const [suggestions, setSuggestions] = useState<{ text: string; category: string; location: string | null }[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [openPrompt, setOpenPrompt] = useState<Prompt | null>(null);
  const [manual, setManual] = useState({ engine: "google_ai_overview", response_text: "", citations: "" });
  const [msg, setMsg] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const { data: prompts } = useApiQuery<Prompt[]>(current ? "/geo/prompts" : null, { project_id: current?.id, category: cat || undefined });
  const { data: providers } = useApiQuery<Provider[]>("/geo/providers");
  const { data: results } = useApiQuery<Result[]>(openPrompt ? "/geo/results" : null, { prompt_id: openPrompt?.id });
  const job = useJob(jobId, (j) => setMsg({ tone: j.status === "succeeded" ? "success" : "error", text: j.status === "succeeded" ? `Collected ${j.result.completed} answers${j.result.failed ? `, ${j.result.failed} failed (not charged)` : ""}.` : j.error ?? "Monitoring failed" }));
  const m = useApiMutation((fn: () => Promise<unknown>) => fn(), ["/geo", "/billing"]);
  const run = (fn: () => Promise<unknown>, ok?: string) => m.mutate(fn, { onError: (e) => setMsg({ tone: "error", text: errorMessage(e) }), onSuccess: () => ok && setMsg({ tone: "success", text: ok }) });
  const apiProviders = (providers ?? []).filter((p) => p.mode === "api");

  if (!current) return (<><PageHeader title="GEO prompts" actions={<GeoProjectPicker />} /><Empty title="Create a GEO project first" /></>);
  return (
    <>
      <PageHeader title="GEO prompts" description="The questions you track across AI answer engines, and every answer collected." actions={<GeoProjectPicker />} />
      {msg && <Notice tone={msg.tone} className="mb-4">{msg.text}</Notice>}
      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <Panel title="Prompt library" actions={
          <>
            <Select aria-label="Category" className="w-40" value={cat} onChange={(e) => setCat(e.target.value)} options={[{ value: "", label: "All categories" }, ...CATS.map((c) => ({ value: c, label: c[0].toUpperCase() + c.slice(1) }))]} />
            {canWrite && <Button variant="primary" loading={m.isPending || (job.data?.status !== undefined && !["succeeded", "failed"].includes(job.data.status))}
              onClick={() => run(async () => { const r = await api.post<{ job_id: string; queries: number }>("/geo/monitoring/run", { project_id: current.id }); setJobId(r.job_id); setMsg({ tone: "success", text: `Running ${r.queries} queries…` }); })}>Run monitoring now</Button>}
          </>
        }>
          {!prompts?.length ? <Empty title="No prompts yet" body="Add questions your customers ask, or let the GEO agent suggest some." /> : (
            <Table head={["Question", "Category", ...apiProviders.map((p) => p.name.split(" (")[0]), ""]}>
              {prompts.map((p) => (
                <tr key={p.id} className={cn(!p.active && "opacity-50")}>
                  <td><button className="text-left hover:underline" onClick={() => setOpenPrompt(p)}>{p.text}</button> {p.source === "ai_suggested" && <Tag tone="ai">suggested</Tag>}</td>
                  <td className="capitalize">{p.category}</td>
                  {apiProviders.map((pr) => {
                    const l = p.latest[pr.id];
                    return <td key={pr.id}>{!l ? <span className="text-faint">—</span> : l.mentioned ? <span className="text-leaf">Mentioned{l.position ? ` #${l.position}` : ""}{l.cited ? ", cited" : ""}</span> : <span className="text-danger">Not mentioned</span>}</td>;
                  })}
                  <td>{canWrite && <button className="text-xs text-muted hover:text-ink" onClick={() => run(() => api.patch(`/geo/prompts/${p.id}`, { active: !p.active }))}>{p.active ? "Pause" : "Resume"}</button>}</td>
                </tr>
              ))}
            </Table>
          )}
        </Panel>
        <div className="space-y-5">
          {canWrite && (
            <Panel title="Add a question">
              <div className="space-y-3">
                <Field label="Question"><Textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="Best thali in Pune?" /></Field>
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Category"><Select value={newCat} onChange={(e) => setNewCat(e.target.value)} options={CATS.map((c) => ({ value: c, label: c }))} /></Field>
                  <Field label="Location"><Input value={location} onChange={(e) => setLocation(e.target.value)} /></Field>
                </div>
                <Button variant="primary" className="w-full" disabled={text.trim().length < 3} onClick={() => run(async () => { await api.post("/geo/prompts", { project_id: current.id, text, category: newCat, location: location || null }); setText(""); })}>Add question</Button>
                <Button className="w-full" onClick={() => run(async () => setSuggestions((await api.post<{ suggestions: typeof suggestions }>("/geo/prompts/suggest", { project_id: current.id })).suggestions))}>Suggest questions · 2 credits</Button>
                {suggestions.length > 0 && (
                  <ul className="space-y-1.5">
                    {suggestions.map((s) => (
                      <li key={s.text} className="flex items-start justify-between gap-2 text-[13px]">
                        <span>{s.text} <span className="text-xs text-muted">{s.category}</span></span>
                        <button className="shrink-0 text-xs underline" onClick={() => run(async () => { await api.post("/geo/prompts", { project_id: current.id, text: s.text, category: s.category, location: s.location, source: "ai_suggested" }); setSuggestions(suggestions.filter((x) => x.text !== s.text)); })}>Track</button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Panel>
          )}
          <Panel title="Answer engines">
            <ul className="space-y-2 text-[13px]">
              {providers?.map((p) => (
                <li key={p.id}><p className="font-medium">{p.name}</p>
                  <p className="text-xs text-muted">{p.mode === "manual" ? p.note : p.available ? "Queried through its official API" : "Not configured on this server"}</p></li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
      <Drawer open={Boolean(openPrompt)} onClose={() => setOpenPrompt(null)} title={openPrompt?.text ?? ""} width="max-w-2xl">
        <div className="space-y-5">
          {canWrite && (
            <details className="rounded-md border border-rule p-3">
              <summary className="cursor-pointer text-[13px] font-medium">Import an answer you saw (for engines without an API)</summary>
              <div className="mt-3 space-y-3">
                <Field label="Engine"><Select value={manual.engine} onChange={(e) => setManual({ ...manual, engine: e.target.value })} options={[["google_ai_overview", "Google AI Overviews / AI Mode"], ["copilot", "Microsoft Copilot"], ["chatgpt", "ChatGPT"], ["gemini", "Gemini"], ["other", "Other"]].map(([value, label]) => ({ value, label }))} /></Field>
                <Field label="Answer text"><Textarea rows={5} value={manual.response_text} onChange={(e) => setManual({ ...manual, response_text: e.target.value })} /></Field>
                <Field label="Cited links" hint="One per line"><Textarea rows={2} value={manual.citations} onChange={(e) => setManual({ ...manual, citations: e.target.value })} /></Field>
                <Button variant="primary" disabled={!manual.response_text} onClick={() => run(async () => { await api.post("/geo/results/manual", { prompt_id: openPrompt!.id, engine: manual.engine, response_text: manual.response_text, citations: manual.citations.split("\n").map((s) => s.trim()).filter(Boolean) }); setManual({ ...manual, response_text: "", citations: "" }); }, "Answer recorded.")}>Save answer</Button>
              </div>
            </details>
          )}
          {!results?.length && <p className="text-[13px] text-muted">No answers collected for this question yet.</p>}
          {results?.map((r) => (
            <article key={r.id} className="space-y-2 rounded-md border border-rule p-3">
              <div className="flex flex-wrap items-center gap-2 text-[13px]">
                <b>{r.provider.startsWith("manual:") ? `${r.provider.slice(7).replace(/_/g, " ")} (imported)` : r.provider.replace("_", " ")}</b>
                <span className="text-xs text-muted">{new Date(r.observed_at).toLocaleString("en-IN")}</span>
                {r.status === "failed" ? <Tag>failed: {r.error}</Tag> : (
                  <>
                    <Tag>{r.brand_mentioned ? `mentioned${r.brand_position ? ` #${r.brand_position}` : ""}` : "not mentioned"}</Tag>
                    {r.brand_cited && <Tag>site cited</Tag>}
                    {Object.entries(r.competitor_mentions).map(([n, c]) => <Tag key={n}>{n} ×{c}</Tag>)}
                  </>
                )}
              </div>
              {r.response_text && <p className="max-h-48 overflow-y-auto whitespace-pre-line text-[13px] text-ink-2">{r.response_text}</p>}
              {r.citations.length > 0 && <ul className="text-xs text-muted">{r.citations.map((c) => <li key={c.url} className="truncate"><a href={c.url} target="_blank" rel="noreferrer" className="underline">{c.title ?? c.url}</a></li>)}</ul>}
            </article>
          ))}
        </div>
      </Drawer>
    </>
  );
}
