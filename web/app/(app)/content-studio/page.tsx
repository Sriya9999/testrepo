"use client";

import type { ContentAsset } from "@marketingos/api-client";
import { Copy, Download, Image as ImageIcon, Layers, Send, Wand2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { ContentEditor, ContentView } from "@/components/content-body";
import { Button, cn, Empty, Field, Input, Notice, PageHeader, Panel, Select, Spinner, StatusBadge, Tabs, Tag } from "@/components/ui";
import { api, downloadFile } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan, useJob } from "@/lib/hooks";

type TabKey = "posts" | "carousels" | "reels" | "stories" | "blogs" | "ads" | "email";
const TABS: { value: TabKey; label: string; types: [string, string, string][] }[] = [
  { value: "posts", label: "Posts", types: [["instagram", "post", "Instagram post"], ["facebook", "post", "Facebook post"], ["linkedin", "post", "LinkedIn post"]] },
  { value: "carousels", label: "Carousels", types: [["instagram", "carousel", "Instagram carousel"]] },
  { value: "reels", label: "Reels", types: [["instagram", "reel", "Reel script & storyboard"]] },
  { value: "stories", label: "Stories", types: [["instagram", "story", "Instagram story"]] },
  { value: "blogs", label: "Blogs & pages", types: [["blog", "article", "SEO article"], ["website", "landing_page", "Landing page"], ["geo", "answer_article", "AI-search answer article"], ["geo", "faq", "FAQ"]] },
  { value: "ads", label: "Advertisements", types: [["instagram", "ad", "Instagram ad"], ["facebook", "ad", "Facebook ad"], ["google_ads", "search_ad", "Google search ad"]] },
  { value: "email", label: "Email", types: [["email", "campaign", "Email campaign"]] },
];

interface Formats { formats: Record<string, { format: string; label: string; credits: number; sections: string[] }[]>; image_credits: number; variation_credits: number; provider: string }
interface Brand { id: string; name: string; voice: string; approved_ctas: string[]; prohibited_claims: string[]; colors: string[]; target_customers: string }

function Studio() {
  const router = useRouter();
  const params = useSearchParams();
  const canWrite = useCan("content:write");
  const [tab, setTab] = useState<TabKey>("posts");
  const [type, setType] = useState("instagram:post");
  const [selected, setSelected] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [imageJob, setImageJob] = useState<string | null>(null);
  const [editing, setEditing] = useState<Record<string, any> | null>(null);
  const [busySection, setBusySection] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [brief, setBrief] = useState({ brand_id: "", topic: "", product: "", audience: "", objective: "engagement", tone: "", language: "en",
    keywords: "", cta: "", dimensions: "square", number_of_slides: 5, variations: 1, question: "" });

  const { data: formats } = useApiQuery<Formats>("/content/formats");
  const { data: brands } = useApiQuery<Brand[]>("/brands");
  const [platform, format] = type.split(":");
  const { data: library, refetch } = useApiQuery<ContentAsset[]>("/content");
  const { data: asset, refetch: refetchAsset } = useApiQuery<ContentAsset>(selected ? `/content/${selected}` : null, undefined, {
    refetchInterval: (q) => ((q.state.data as ContentAsset | undefined)?.generation_status === "pending" ? 1200 : false),
  });
  useJob(jobId, () => { refetch(); refetchAsset(); setJobId(null); });
  useJob(imageJob, () => { refetchAsset(); setImageJob(null); });

  useEffect(() => { setType(TABS.find((t) => t.value === tab)!.types[0].slice(0, 2).join(":")); }, [tab]);
  useEffect(() => {
    const question = params.get("question");
    if (question) { setTab("blogs"); setTimeout(() => setType("geo:answer_article"), 0); setBrief((b) => ({ ...b, question })); }
  }, [params]);
  useEffect(() => { setEditing(null); }, [selected]);

  const typeInfo = formats?.formats[platform]?.find((f) => f.format === format);
  const cost = (typeInfo?.credits ?? 0) + (brief.variations - 1) * (formats?.variation_credits ?? 0);
  const brand = brands?.find((b) => b.id === (asset?.brand_id ?? brief.brand_id)) ?? brands?.[0];
  const tabTypes = TABS.find((t) => t.value === tab)!.types;
  const items = useMemo(() => (library ?? []).filter((a) => tabTypes.some(([p, f]) => a.platform === p && a.format === f)), [library, tabTypes]);

  const generate = async () => {
    setError("");
    try {
      const r = await api.post<{ job_id: string; content_id: string }>("/content/generate", {
        ...brief, platform, format, brand_id: brief.brand_id || null, keywords: brief.keywords.split(",").map((k) => k.trim()).filter(Boolean),
        question: brief.question || null,
      });
      setJobId(r.job_id);
      setSelected(r.content_id);
      refetch();
    } catch (e) { setError(errorMessage(e)); }
  };
  const act = useApiMutation(async (fn: () => Promise<unknown>) => fn(), ["/content", "/approvals"]);
  const run = (fn: () => Promise<unknown>) => act.mutate(fn, { onError: (e) => setError(errorMessage(e)), onSuccess: () => { setError(""); refetchAsset(); } });

  return (
    <>
      <PageHeader title="Content studio" description="Generate on-brand drafts, edit them, keep every version, and send them for approval."
        actions={formats && <span className="text-xs text-muted">Writer: {formats.provider === "offline" ? "offline drafts (connect an AI model for full quality)" : formats.provider}</span>} />
      <Tabs value={tab} onChange={(v) => { setTab(v); setSelected(null); }} tabs={TABS.map((t) => ({ value: t.value, label: t.label }))} />
      <div className="mt-5 grid gap-5 xl:grid-cols-[300px_1fr_260px]">
        {/* Left: generation controls */}
        <Panel title="Brief">
          <div className="space-y-3">
            <Field label="Type"><Select value={type} onChange={(e) => setType(e.target.value)} options={tabTypes.map(([p, f, l]) => ({ value: `${p}:${f}`, label: l }))} /></Field>
            <Field label="Brand"><Select value={brief.brand_id} onChange={(e) => setBrief({ ...brief, brand_id: e.target.value })}
              options={[{ value: "", label: "Default brand" }, ...(brands ?? []).map((b) => ({ value: b.id, label: b.name }))]} /></Field>
            {platform === "geo" && <Field label="Question to answer"><Input value={brief.question} onChange={(e) => setBrief({ ...brief, question: e.target.value })} /></Field>}
            <Field label="Topic or occasion"><Input value={brief.topic} onChange={(e) => setBrief({ ...brief, topic: e.target.value })} placeholder="Weekend special" /></Field>
            <Field label="Product or service"><Input value={brief.product} onChange={(e) => setBrief({ ...brief, product: e.target.value })} /></Field>
            <Field label="Audience"><Input value={brief.audience} onChange={(e) => setBrief({ ...brief, audience: e.target.value })} placeholder="From your brand profile" /></Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Objective"><Select value={brief.objective} onChange={(e) => setBrief({ ...brief, objective: e.target.value })}
                options={["engagement", "awareness", "traffic", "leads", "sales"].map((v) => ({ value: v, label: v[0].toUpperCase() + v.slice(1) }))} /></Field>
              <Field label="Language"><Select value={brief.language} onChange={(e) => setBrief({ ...brief, language: e.target.value })}
                options={[["en", "English"], ["hi", "Hindi"], ["mr", "Marathi"], ["ta", "Tamil"], ["te", "Telugu"], ["bn", "Bengali"]].map(([value, label]) => ({ value, label }))} /></Field>
            </div>
            <Field label="Tone"><Input value={brief.tone} onChange={(e) => setBrief({ ...brief, tone: e.target.value })} placeholder={brand?.voice || "premium, friendly…"} /></Field>
            <Field label="Keywords" hint="Comma separated"><Input value={brief.keywords} onChange={(e) => setBrief({ ...brief, keywords: e.target.value })} /></Field>
            <Field label="Call to action"><Input value={brief.cta} onChange={(e) => setBrief({ ...brief, cta: e.target.value })} placeholder={brand?.approved_ctas?.[0]} /></Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Size"><Select value={brief.dimensions} onChange={(e) => setBrief({ ...brief, dimensions: e.target.value })}
                options={[["square", "1:1"], ["portrait", "4:5"], ["story", "9:16"], ["landscape", "1.91:1"]].map(([value, label]) => ({ value, label }))} /></Field>
              <Field label="Variations"><Select value={String(brief.variations)} onChange={(e) => setBrief({ ...brief, variations: Number(e.target.value) })}
                options={[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }))} /></Field>
            </div>
            {format === "carousel" && <Field label="Slides"><Input type="number" min={2} max={10} value={brief.number_of_slides} onChange={(e) => setBrief({ ...brief, number_of_slides: Number(e.target.value) })} /></Field>}
            <Button variant="primary" className="w-full" disabled={!canWrite} loading={Boolean(jobId)} onClick={generate}>
              <Wand2 className="size-4" aria-hidden /> Generate · {cost} credits
            </Button>
          </div>
        </Panel>

        {/* Center: preview / editor */}
        <div className="min-w-0 space-y-4">
          {error && <Notice tone="error">{error}</Notice>}
          {!asset && <Empty title="No draft open" body="Fill in the brief and generate, or open something from the library below." />}
          {asset && (
            <Panel
              title={<span className="flex flex-wrap items-center gap-2">{asset.title} <StatusBadge status={asset.status} /></span>}
              description={`${asset.platform} · ${asset.format} · version ${asset.current_version}`}
              actions={asset.generation_status === "ready" && (editing ? (
                <>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Discard</Button>
                  <Button size="sm" variant="primary" loading={act.isPending} onClick={() => run(async () => { await api.patch(`/content/${asset.id}`, { body: editing }); setEditing(null); })}>Save as new version</Button>
                </>
              ) : canWrite && <Button size="sm" onClick={() => setEditing(asset.body)}>Edit</Button>)}
            >
              {asset.generation_status === "pending" && <Spinner label="Writing your draft" />}
              {asset.generation_status === "failed" && <Notice tone="error">Generation failed: {asset.generation_error}. No credits were charged.</Notice>}
              {asset.generation_status === "ready" && (editing ? <ContentEditor body={editing} onChange={setEditing} /> : (
                <ContentView body={asset.body} sections={typeInfo?.sections ?? []} busySection={busySection}
                  onRegenerate={canWrite ? (s) => { setBusySection(s); run(async () => { try { await api.post(`/content/${asset.id}/regenerate`, { section: s }); } finally { setBusySection(null); } }); } : undefined} />
              ))}
              {asset.quality?.issues && asset.quality.issues.length > 0 && (
                <div className="mt-4 space-y-1.5 border-t border-rule pt-3">
                  {asset.quality.issues.map((i, n) => <Notice key={n} tone={i.level === "error" ? "error" : "warning"}>{i.message}</Notice>)}
                </div>
              )}
            </Panel>
          )}
          {asset?.versions && asset.versions.length > 1 && (
            <Panel title="Versions">
              <ul className="divide-y divide-rule">
                {asset.versions.slice().reverse().map((v) => (
                  <li key={v.version} className="flex items-center justify-between gap-3 py-2 text-[13px]">
                    <span><b className="tabular">v{v.version}</b> · {v.label ?? v.source} <span className="text-xs text-muted">{new Date(v.created_at).toLocaleString("en-IN")}</span></span>
                    {v.version === asset.current_version ? <Tag>current</Tag> : (
                      <Button size="sm" variant="ghost" onClick={() => run(() => api.post(`/content/${asset.id}/versions/${v.version}/select`))}>Use this version</Button>
                    )}
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>

        {/* Right: brand + AI tools */}
        <aside className="space-y-4">
          {asset?.generation_status === "ready" && (
            <Panel title="Actions">
              <div className="grid gap-2">
                <Button variant="signoff" disabled={!canWrite || asset.status === "in_review" || asset.status === "approved"} onClick={() => run(() => api.post(`/content/${asset.id}/submit`))}>
                  <Send className="size-4" aria-hidden /> {asset.status === "in_review" ? "Waiting for approval" : asset.status === "approved" ? "Approved" : "Submit for approval"}
                </Button>
                <Button disabled={!canWrite || Boolean(imageJob)} loading={Boolean(imageJob)} onClick={() => run(async () => {
                  const r = await api.post<{ job_id: string }>("/content/images/generate", {
                    prompt: asset.body.image_prompt || asset.body.slides?.[0]?.image_prompt || asset.title, content_id: asset.id,
                    brand_id: asset.brand_id, dimensions: asset.brief.dimensions ?? "square" });
                  setImageJob(r.job_id);
                })}>
                  <ImageIcon className="size-4" aria-hidden /> Generate image · {formats?.image_credits} cr
                </Button>
                <Button disabled={!canWrite} onClick={() => run(async () => { const r = await api.post<{ job_id: string }>("/content/variations", { content_id: asset.id, count: 2 }); setJobId(r.job_id); })}>
                  <Layers className="size-4" aria-hidden /> 2 more variations
                </Button>
                <Link href={`/content-studio/editor/${asset.id}`} className="inline-flex h-9 items-center justify-center rounded-[var(--radius-control)] border border-rule-strong bg-surface text-sm font-medium hover:bg-sunk">Open creative editor</Link>
                {asset.platform === "instagram" && (
                  <Button onClick={() => run(async () => { await api.post("/social/posts", { content_asset_id: asset.id, format: asset.format === "post" ? "image" : asset.format }); router.push("/social/calendar"); })}>Add to calendar</Button>
                )}
                <div className="flex gap-2">
                  <Button size="sm" variant="ghost" onClick={() => run(async () => { const c = await api.post<ContentAsset>(`/content/${asset.id}/duplicate`); setSelected(c.id); })}><Copy className="size-3.5" aria-hidden /> Duplicate</Button>
                  <Button size="sm" variant="ghost" onClick={() => downloadFile(`/content/${asset.id}/export?format=md`, `${asset.title}.md`, "POST")}><Download className="size-3.5" aria-hidden /> Export</Button>
                </div>
              </div>
            </Panel>
          )}
          {brand && (
            <Panel title="Brand memory" description="Used for every draft.">
              <div className="space-y-2 text-[13px]">
                <p className="font-semibold">{brand.name}</p>
                {brand.colors?.length > 0 && <div className="flex gap-1">{brand.colors.map((c) => <span key={c} title={c} className="size-5 rounded border border-rule" style={{ background: c }} />)}</div>}
                {brand.voice && <p><span className="text-muted">Voice: </span>{brand.voice}</p>}
                {brand.approved_ctas?.length > 0 && <p><span className="text-muted">CTAs: </span>{brand.approved_ctas.join(", ")}</p>}
                {brand.prohibited_claims?.length > 0 && <p><span className="text-muted">Never say: </span>{brand.prohibited_claims.join(", ")}</p>}
                <Link href="/settings?tab=brand" className="text-xs underline">Edit brand</Link>
              </div>
            </Panel>
          )}
        </aside>
      </div>

      <Panel title="Library" className="mt-6">
        {items.length ? (
          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((a) => (
              <li key={a.id}>
                <button onClick={() => setSelected(a.id)} className={cn("w-full rounded-md border p-3 text-left hover:border-rule-strong", selected === a.id ? "border-ink" : "border-rule")}>
                  <span className="line-clamp-1 text-[13px] font-medium">{a.title}</span>
                  <span className="mt-1 line-clamp-2 block text-xs text-muted">{a.body?.caption ?? a.body?.title ?? a.body?.primary_text ?? (a.generation_status === "pending" ? "Generating…" : "")}</span>
                  <span className="mt-2 flex items-center gap-2"><StatusBadge status={a.status} /><span className="text-[11px] text-faint">{new Date(a.updated_at).toLocaleDateString("en-IN")}</span></span>
                </button>
              </li>
            ))}
          </ul>
        ) : <p className="text-[13px] text-muted">Nothing in this tab yet.</p>}
      </Panel>
    </>
  );
}

export default function ContentStudioPage() {
  return <Suspense><Studio /></Suspense>;
}
