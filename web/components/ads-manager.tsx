"use client";

import { formatMoney, formatNumber, type Campaign } from "@marketingos/api-client";
import { Check, Plus, Sparkles } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { LineChart, SERIES_COLORS } from "./charts";
import { RangePicker, useDateRange } from "./filters";
import { Button, cn, Drawer, Empty, Field, Input, KeyValue, Notice, Panel, Select, StatusBadge, Table, Tabs, Tag, Textarea, Toggle } from "./ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan } from "@/lib/hooks";

type Platform = "meta" | "google";
interface AdAccount { id: string; name: string; currency: string; mode: string | null; status: string; pages: { id: string; name: string; instagram_user_id?: string }[] }
interface Insights { currency: string; totals: Record<string, number | null>; daily: { date: string; spend_minor: number; clicks: number; results: number }[];
  campaigns: ({ campaign_id: string; name: string } & Record<string, number | null>)[]; sources: string[] }
interface Rec { title: string; action: string; priority: string; type: string; campaign_name: string; requires_approval: boolean; evidence: Record<string, number> }

const META_OBJECTIVES = ["awareness", "traffic", "engagement", "leads", "sales", "app_promotion"];
const GOOGLE_OBJECTIVES = ["traffic", "leads", "sales"];
const CTAS = ["LEARN_MORE", "SHOP_NOW", "SIGN_UP", "BOOK_TRAVEL", "CONTACT_US", "ORDER_NOW", "GET_OFFER", "SUBSCRIBE", "CALL_NOW"];
const pretty = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

function rupeesToMinor(v: string) { const n = Number(v); return Number.isFinite(n) && n > 0 ? Math.round(n * 100) : null; }

/* ---------- campaign wizard ---------------------------------------------------------- */

const META_STEPS = ["Ad account", "Objective", "Name", "Audience", "Location", "Budget & schedule", "Placements", "Creative", "Ad copy", "Review"];
const GOOGLE_STEPS = ["Ad account", "Objective", "Name", "Budget & schedule", "Locations", "Ad groups", "Negative keywords", "Review"];

function Wizard({ platform, accounts, onDone }: { platform: Platform; accounts: AdAccount[]; onDone: (id: string) => void }) {
  const steps = platform === "meta" ? META_STEPS : GOOGLE_STEPS;
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: media } = useApiQuery<{ id: string; url: string; kind: string }[]>("/media", { kind: "image" });
  const [f, setF] = useState({
    ad_account_id: accounts[0]?.id ?? "", objective: "traffic", name: "", daily: "500", start_date: "", end_date: "",
    age_min: 18, age_max: 55, genders: "", interests: "", countries: "IN", cities: "",
    automatic: true, platforms: ["facebook", "instagram"], media_asset_ids: [] as string[], page_id: accounts[0]?.pages?.[0]?.id ?? "",
    primary_text: "", headline: "", description: "", cta_type: "LEARN_MORE", link_url: "", pixel_id: "",
    locations: "2356:India", groups: [{ name: "Main", keywords: "", headlines: "", descriptions: "", final_url: "" }], negatives: "free\njobs\ncareer",
    bidding: "maximize_clicks",
  });
  const acct = accounts.find((a) => a.id === f.ad_account_id);
  const set = (k: keyof typeof f, v: unknown) => setF({ ...f, [k]: v });

  const config = () => platform === "meta" ? {
    audience: { age_min: f.age_min, age_max: f.age_max, genders: f.genders ? [Number(f.genders)] : [],
      interests: f.interests.split(",").map((s) => s.trim()).filter(Boolean).map((name) => ({ name })) },
    geo: { countries: f.countries.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean),
      cities: f.cities.split(",").map((s) => s.trim()).filter(Boolean).map((name) => ({ name, radius_km: 15 })) },
    placements: { automatic: f.automatic, publisher_platforms: f.platforms },
    copy: { primary_text: f.primary_text, headline: f.headline, description: f.description, cta_type: f.cta_type, link_url: f.link_url },
    media_asset_ids: f.media_asset_ids, page_id: f.page_id || null,
    instagram_user_id: acct?.pages.find((p) => p.id === f.page_id)?.instagram_user_id ?? null, pixel_id: f.pixel_id || null,
  } : {
    ad_groups: f.groups.map((g) => ({
      name: g.name, final_url: g.final_url, paths: [],
      keywords: g.keywords.split("\n").map((k) => k.trim()).filter(Boolean).map((k) => k.startsWith("[") ? { text: k.slice(1, -1), match_type: "EXACT" }
        : k.startsWith('"') ? { text: k.slice(1, -1), match_type: "PHRASE" } : { text: k, match_type: "BROAD" }),
      headlines: g.headlines.split("\n").map((s) => s.trim()).filter(Boolean), descriptions: g.descriptions.split("\n").map((s) => s.trim()).filter(Boolean),
    })),
    negative_keywords: f.negatives.split("\n").map((s) => s.trim()).filter(Boolean),
    locations: f.locations.split(",").map((s) => s.trim()).filter(Boolean).map((s) => { const [id, name] = s.split(":"); return { id, name: name ?? id }; }),
    bidding: f.bidding,
  };

  const create = async (requestApproval: boolean) => {
    setBusy(true); setError("");
    try {
      const c = await api.post<Campaign>(`/ads/${platform}/campaigns/drafts`, {
        ad_account_id: f.ad_account_id || null, name: f.name || `${pretty(f.objective)} campaign`, objective: f.objective,
        daily_budget_minor: rupeesToMinor(f.daily), start_date: f.start_date || null, end_date: f.end_date || null, config: config(),
      });
      if (requestApproval) await api.post(`/ads/${platform}/campaigns/${c.id}/request-approval`, { activate: true });
      onDone(c.id);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };

  const s = steps[step];
  return (
    <div className="grid gap-6 md:grid-cols-[180px_1fr]">
      <ol className="space-y-1">
        {steps.map((name, i) => (
          <li key={name}>
            <button onClick={() => setStep(i)} className={cn("flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[13px]", i === step ? "bg-sunk font-semibold" : "text-muted")}>
              <span className={cn("grid size-5 place-items-center rounded-full text-[11px]", i < step ? "bg-leaf text-white" : "bg-sunk")}>{i < step ? <Check className="size-3" /> : i + 1}</span>{name}
            </button>
          </li>
        ))}
        <li className="px-2 pt-2 text-[11px] text-faint">Then: approval, then submission to {platform === "meta" ? "Meta" : "Google"}.</li>
      </ol>
      <div className="space-y-4">
        <h3 className="text-base font-semibold">{s}</h3>
        {error && <Notice tone="error">{error}</Notice>}
        {s === "Ad account" && (accounts.length ? (
          <Field label="Ad account"><Select value={f.ad_account_id} onChange={(e) => set("ad_account_id", e.target.value)} options={accounts.map((a) => ({ value: a.id, label: `${a.name}${a.mode === "sandbox" ? " (sandbox)" : ""} · ${a.currency}` }))} /></Field>
        ) : <Notice tone="warning">Connect an ad account under Integrations first. You can still save a draft.</Notice>)}
        {s === "Objective" && (
          <div className="grid gap-2 sm:grid-cols-3">
            {(platform === "meta" ? META_OBJECTIVES : GOOGLE_OBJECTIVES).map((o) => (
              <button key={o} onClick={() => set("objective", o)} className={cn("rounded-[var(--radius-control)] border px-3 py-2.5 text-left text-sm", f.objective === o ? "border-ink bg-surface font-semibold" : "border-rule-strong text-ink-2")}>{pretty(o)}</button>
            ))}
          </div>
        )}
        {s === "Name" && <Field label="Campaign name"><Input value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="Weekend thali · Traffic · Nov" /></Field>}
        {s === "Audience" && (
          <>
            <div className="grid grid-cols-3 gap-3">
              <Field label="Min age"><Input type="number" min={13} max={65} value={f.age_min} onChange={(e) => set("age_min", Number(e.target.value))} /></Field>
              <Field label="Max age"><Input type="number" min={13} max={65} value={f.age_max} onChange={(e) => set("age_max", Number(e.target.value))} /></Field>
              <Field label="Gender"><Select value={f.genders} onChange={(e) => set("genders", e.target.value)} options={[{ value: "", label: "All" }, { value: "1", label: "Men" }, { value: "2", label: "Women" }]} /></Field>
            </div>
            <Field label="Interests" hint="Comma separated. Matched to Meta's interest list when the campaign is created."><Input value={f.interests} onChange={(e) => set("interests", e.target.value)} /></Field>
          </>
        )}
        {s === "Location" && (
          <>
            <Field label="Countries" hint="ISO codes, comma separated"><Input value={f.countries} onChange={(e) => set("countries", e.target.value)} /></Field>
            <Field label="Cities" hint="Optional; a 15 km radius around each"><Input value={f.cities} onChange={(e) => set("cities", e.target.value)} placeholder="Pune, Mumbai" /></Field>
          </>
        )}
        {s === "Locations" && <Field label="Locations" hint="Google geo target ids with names, e.g. 2356:India, 1007788:Pune"><Input value={f.locations} onChange={(e) => set("locations", e.target.value)} /></Field>}
        {s === "Budget & schedule" && (
          <>
            <Field label={`Daily budget (${acct?.currency ?? "INR"})`} hint="Capped by your workspace's daily spend limit. Nothing is spent until the launch is approved.">
              <Input type="number" min={1} value={f.daily} onChange={(e) => set("daily", e.target.value)} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Start"><Input type="date" value={f.start_date} onChange={(e) => set("start_date", e.target.value)} /></Field>
              <Field label="End (optional)"><Input type="date" value={f.end_date} onChange={(e) => set("end_date", e.target.value)} /></Field>
            </div>
            {platform === "google" && <Field label="Bidding"><Select value={f.bidding} onChange={(e) => set("bidding", e.target.value)} options={[["maximize_clicks", "Maximise clicks"], ["maximize_conversions", "Maximise conversions"], ["manual_cpc", "Manual CPC"]].map(([value, label]) => ({ value, label }))} /></Field>}
          </>
        )}
        {s === "Placements" && (
          <div className="space-y-3">
            <label className="flex items-center gap-3 text-sm"><Toggle checked={f.automatic} onChange={(v) => set("automatic", v)} label="Automatic placements" /> Automatic placements (recommended)</label>
            {!f.automatic && ["facebook", "instagram", "messenger", "audience_network"].map((p) => (
              <label key={p} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={f.platforms.includes(p)} onChange={(e) => set("platforms", e.target.checked ? [...f.platforms, p] : f.platforms.filter((x) => x !== p))} /> {pretty(p)}
              </label>
            ))}
          </div>
        )}
        {s === "Creative" && (
          <>
            <Field label="Facebook Page"><Select value={f.page_id} onChange={(e) => set("page_id", e.target.value)} options={[{ value: "", label: "Choose…" }, ...(acct?.pages ?? []).map((p) => ({ value: p.id, label: p.name }))]} /></Field>
            <Field label="Image" hint="Generate one in the Content studio, or upload in Social → Calendar.">
              <div className="flex flex-wrap gap-2">
                {(media ?? []).slice(0, 12).map((m) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <button key={m.id} onClick={() => set("media_asset_ids", [m.id])} className={cn("size-20 overflow-hidden rounded border", f.media_asset_ids.includes(m.id) ? "border-ink ring-2 ring-ink/30" : "border-rule")}><img src={m.url} alt="" className="size-full object-cover" /></button>
                ))}
                {!media?.length && <p className="text-[13px] text-muted">No images yet.</p>}
              </div>
            </Field>
          </>
        )}
        {s === "Ad copy" && (
          <>
            <Field label="Primary text" hint={`${f.primary_text.length} characters; over 125 gets truncated`}><Textarea rows={3} value={f.primary_text} onChange={(e) => set("primary_text", e.target.value)} /></Field>
            <Field label="Headline"><Input value={f.headline} onChange={(e) => set("headline", e.target.value)} /></Field>
            <Field label="Description"><Input value={f.description} onChange={(e) => set("description", e.target.value)} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Button"><Select value={f.cta_type} onChange={(e) => set("cta_type", e.target.value)} options={CTAS.map((c) => ({ value: c, label: pretty(c.toLowerCase()) }))} /></Field>
              <Field label="Destination URL"><Input value={f.link_url} onChange={(e) => set("link_url", e.target.value)} placeholder="https://" /></Field>
            </div>
            {f.objective === "sales" && <Field label="Meta pixel id"><Input value={f.pixel_id} onChange={(e) => set("pixel_id", e.target.value)} /></Field>}
          </>
        )}
        {s === "Ad groups" && f.groups.map((g, i) => (
          <div key={i} className="space-y-2 rounded-md border border-rule p-3">
            <div className="grid grid-cols-2 gap-2">
              <Field label="Ad group name"><Input value={g.name} onChange={(e) => { const groups = [...f.groups]; groups[i] = { ...g, name: e.target.value }; set("groups", groups); }} /></Field>
              <Field label="Final URL"><Input value={g.final_url} onChange={(e) => { const groups = [...f.groups]; groups[i] = { ...g, final_url: e.target.value }; set("groups", groups); }} /></Field>
            </div>
            {(["keywords", "headlines", "descriptions"] as const).map((k) => (
              <Field key={k} label={pretty(k)} hint={k === "keywords" ? 'One per line. "phrase", [exact], or plain for broad.' : k === "headlines" ? "3–15, max 30 characters each" : "2–4, max 90 characters each"}>
                <Textarea rows={k === "keywords" ? 4 : 3} value={g[k]} onChange={(e) => { const groups = [...f.groups]; groups[i] = { ...g, [k]: e.target.value }; set("groups", groups); }} />
              </Field>
            ))}
          </div>
        ))}
        {s === "Ad groups" && <Button size="sm" onClick={() => set("groups", [...f.groups, { name: `Group ${f.groups.length + 1}`, keywords: "", headlines: "", descriptions: "", final_url: f.groups[0].final_url }])}>Add ad group</Button>}
        {s === "Negative keywords" && <Field label="Negative keywords" hint="One per line. Searches containing these won't show your ads."><Textarea rows={6} value={f.negatives} onChange={(e) => set("negatives", e.target.value)} /></Field>}
        {s === "Review" && (
          <KeyValue items={[
            ["Account", acct?.name ?? "—"], ["Objective", pretty(f.objective)], ["Name", f.name || "—"],
            ["Daily budget", formatMoney(rupeesToMinor(f.daily), acct?.currency ?? "INR")], ["Schedule", f.start_date ? `${f.start_date} → ${f.end_date || "ongoing"}` : "Starts when approved"],
            ...(platform === "meta" ? [["Audience", `${f.age_min}–${f.age_max}, ${f.countries}${f.cities ? `, ${f.cities}` : ""}`], ["Copy", f.headline || "—"]] as [string, string][]
              : [["Ad groups", f.groups.map((g) => g.name).join(", ")]] as [string, string][]),
          ]} />
        )}
        <div className="flex flex-wrap gap-2 border-t border-rule pt-4">
          {step > 0 && <Button variant="ghost" onClick={() => setStep(step - 1)}>Back</Button>}
          {step < steps.length - 1 ? <Button variant="primary" onClick={() => setStep(step + 1)}>Continue</Button> : (
            <>
              <Button loading={busy} onClick={() => create(false)}>Save draft</Button>
              <Button variant="signoff" loading={busy} onClick={() => create(true)}>Request launch approval</Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------- campaign detail ------------------------------------------------------------ */

function CampaignDetail({ platform, id, onClose }: { platform: Platform; id: string; onClose: () => void }) {
  const canWrite = useCan("ads:write");
  const { data: c, refetch } = useApiQuery<Campaign & { approval_required_for_pause: boolean }>(`/ads/${platform}/campaigns/${id}`, undefined, {
    refetchInterval: (q) => (["approved", "submitting"].includes((q.state.data as Campaign | undefined)?.status ?? "") ? 1500 : false),
  });
  const [budget, setBudget] = useState("");
  const [msg, setMsg] = useState<{ tone: "error" | "success" | "warning"; text: string } | null>(null);
  const m = useApiMutation((fn: () => Promise<unknown>) => fn(), ["/ads", "/approvals", "/dashboard"]);
  const run = (fn: () => Promise<unknown>, ok?: string) => m.mutate(fn, {
    onError: (e) => setMsg({ tone: "error", text: errorMessage(e) }),
    onSuccess: (r) => { const res = r as { requires_approval?: boolean }; setMsg({ tone: res?.requires_approval ? "warning" : "success", text: res?.requires_approval ? "Sent for approval. Nothing changes on the platform until it's approved." : ok ?? "Done." }); refetch(); },
  });
  useEffect(() => { if (c) setBudget(c.daily_budget_minor ? String(c.daily_budget_minor / 100) : ""); }, [c?.daily_budget_minor]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!c) return null;
  const editable = ["draft", "changes_requested", "failed", "rejected", "pending_approval"].includes(c.status);
  const live = ["active", "paused"].includes(c.status);
  const t = c.last_30_days;

  return (
    <Drawer open onClose={onClose} title={c.name} width="max-w-2xl">
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={c.status} />
          {c.created_by_ai && <Tag tone="ai">AI draft</Tag>}
          {c.config.discovered && <Tag>created outside MarketingOS</Tag>}
          {c.external_id && <span className="text-xs text-muted">Platform id {c.external_id}</span>}
        </div>
        {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
        {c.last_error && <Notice tone="error">{c.last_error}</Notice>}
        {editable && c.validation_errors && c.validation_errors.length > 0 && (
          <Notice tone="warning"><p className="font-medium">Before this can be approved:</p><ul className="list-disc pl-4">{c.validation_errors.map((e) => <li key={e}>{e}</li>)}</ul></Notice>
        )}
        {t && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[["Spend", formatMoney(t.spend_minor, c.currency)], ["Clicks", formatNumber(t.clicks)], ["Results", formatNumber(t.results)], ["CPA", formatMoney(t.cpa_minor, c.currency)]].map(([k, v]) => (
              <div key={k} className="rounded-md border border-rule p-2.5"><p className="text-xs text-muted">{k}</p><p className="text-base font-bold tabular">{v}</p></div>
            ))}
          </div>
        )}
        <KeyValue items={[
          ["Objective", pretty(c.objective)], ["Daily budget", formatMoney(c.daily_budget_minor, c.currency)],
          ["Schedule", c.start_date ? `${c.start_date} → ${c.end_date ?? "ongoing"}` : "—"],
          ...(c.platform === "meta" ? [["Audience", `${c.config.audience?.age_min}–${c.config.audience?.age_max}, ${(c.config.geo?.countries ?? []).join(", ")}`],
            ["Copy", c.config.copy?.primary_text ?? "—"], ["Headline", c.config.copy?.headline ?? "—"]] as [string, string][]
            : [["Ad groups", (c.config.ad_groups ?? []).map((g: { name: string; keywords: unknown[] }) => `${g.name} (${g.keywords.length} keywords)`).join(", ") || "—"],
              ["Negatives", (c.config.negative_keywords ?? []).join(", ") || "—"]] as [string, string][]),
          ...(c.config.ai_reasoning ? [["AI reasoning", c.config.ai_reasoning]] as [string, string][] : []),
        ]} />
        {canWrite && (
          <div className="flex flex-wrap gap-2 border-t border-rule pt-4">
            {editable && <Button variant="signoff" loading={m.isPending} onClick={() => run(() => api.post(`/ads/${platform}/campaigns/${c.id}/request-approval`, { activate: true }), "Sent for approval.")}>Request launch approval</Button>}
            {c.status === "failed" && <Button onClick={() => run(() => api.post(`/ads/${platform}/campaigns/${c.id}/submit`), "Resubmitted.")}>Retry submission</Button>}
            {c.status === "active" && <Button onClick={() => run(() => api.post(`/ads/${platform}/campaigns/${c.id}/pause`), "Pausing.")}>{c.approval_required_for_pause ? "Request pause" : "Pause"}</Button>}
            {c.status === "paused" && <Button onClick={() => run(() => api.post(`/ads/${platform}/campaigns/${c.id}/activate`))}>Request activation</Button>}
            <Button variant="ghost" onClick={() => run(() => api.post(`/ads/${platform}/campaigns/${c.id}/duplicate`), "Duplicated as a new draft.")}>Duplicate</Button>
          </div>
        )}
        {canWrite && (editable || live) && (
          <div className="flex items-end gap-2">
            <Field label={`Daily budget (${c.currency})`} hint={live ? "Increases need approval; decreases apply right away." : undefined} className="flex-1">
              <Input type="number" value={budget} onChange={(e) => setBudget(e.target.value)} />
            </Field>
            <Button onClick={() => run(() => api.patch(`/ads/${platform}/campaigns/${c.id}`, { daily_budget_minor: rupeesToMinor(budget) }), "Budget updated.")}>Update budget</Button>
          </div>
        )}
        {c.approvals && c.approvals.length > 0 && (
          <div><p className="mb-1.5 text-xs font-medium text-muted">Approval history</p>
            <ul className="space-y-1 text-[13px]">{c.approvals.map((a) => <li key={a.id} className="flex justify-between gap-2"><span className="truncate">{a.title}</span><StatusBadge status={a.status} /></li>)}</ul></div>
        )}
        {c.entities && c.entities.length > 0 && (
          <div><p className="mb-1.5 text-xs font-medium text-muted">On the platform</p>
            <ul className="space-y-1 text-[13px]">{c.entities.map((e) => <li key={e.external_id}>{pretty(e.level)} · {e.external_id} · {e.status}</li>)}</ul></div>
        )}
        {c.submission_log && c.submission_log.length > 0 && (
          <details className="text-[13px]"><summary className="cursor-pointer text-muted">Execution log</summary>
            <ul className="mt-2 space-y-1">{c.submission_log.map((l, i) => <li key={i}><span className="text-xs text-muted tabular">{new Date(l.at).toLocaleString("en-IN")}</span> {l.event} {l.note ? `· ${String(l.note)}` : ""}</li>)}</ul></details>
        )}
      </div>
    </Drawer>
  );
}

/* ---------- AI draft ---------------------------------------------------------------- */

function AiDraft({ platform, onDone }: { platform: Platform; onDone: (id: string) => void }) {
  const [f, setF] = useState({ objective: "traffic", product: "", audience: "", location: "", website: "", keywords: "", daily: "500" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="space-y-3">
      <p className="text-[13px] text-muted">The {platform === "meta" ? "Meta Ads" : "SEM"} agent drafts the structure, targeting and copy from your brand profile. Costs 5 credits; you review everything before anything is submitted.</p>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Objective"><Select value={f.objective} onChange={(e) => setF({ ...f, objective: e.target.value })} options={(platform === "meta" ? META_OBJECTIVES : GOOGLE_OBJECTIVES).map((o) => ({ value: o, label: pretty(o) }))} /></Field>
        <Field label="Daily budget (₹)"><Input type="number" value={f.daily} onChange={(e) => setF({ ...f, daily: e.target.value })} /></Field>
        <Field label="Product or service"><Input value={f.product} onChange={(e) => setF({ ...f, product: e.target.value })} /></Field>
        <Field label="Location"><Input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
        <Field label="Website"><Input value={f.website} onChange={(e) => setF({ ...f, website: e.target.value })} placeholder="https://" /></Field>
        {platform === "google" ? <Field label="Seed keywords" hint="Comma separated"><Input value={f.keywords} onChange={(e) => setF({ ...f, keywords: e.target.value })} /></Field>
          : <Field label="Audience"><Input value={f.audience} onChange={(e) => setF({ ...f, audience: e.target.value })} /></Field>}
      </div>
      <Button variant="primary" loading={busy} onClick={async () => {
        setBusy(true); setError("");
        try {
          const c = await api.post<Campaign>(`/ads/${platform}/campaigns/generate`, { ...f, daily_budget_minor: rupeesToMinor(f.daily), keywords: f.keywords.split(",").map((k) => k.trim()).filter(Boolean), location: f.location || null });
          onDone(c.id);
        } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
      }}><Sparkles className="size-4" aria-hidden /> Draft campaign</Button>
    </div>
  );
}

/* ---------- page ------------------------------------------------------------------- */

export function AdsManager({ platform }: { platform: Platform }) {
  const params = useSearchParams();
  const canWrite = useCan("ads:write");
  const [tab, setTab] = useState("overview");
  const [range, setRange] = useDateRange(30);
  const [open, setOpen] = useState<string | null>(params.get("campaign"));
  const [creating, setCreating] = useState<"wizard" | "ai" | null>(null);
  const { data: accounts } = useApiQuery<AdAccount[]>(`/ads/${platform}/accounts`);
  const { data: campaigns } = useApiQuery<Campaign[]>(`/ads/${platform}/campaigns`);
  const { data: insights } = useApiQuery<Insights>(`/ads/${platform}/insights`, { start: range.start, end: range.end });
  const { data: recs } = useApiQuery<{ recommendations: Rec[]; note: string | null }>(`/ads/${platform}/recommendations`);
  const sync = useApiMutation(() => api.post(`/ads/${platform}/sync`), ["/ads"]);
  const name = platform === "meta" ? "Meta Ads" : "Google Ads";
  const cur = insights?.currency ?? "INR";
  const tabs = platform === "meta"
    ? [["overview", "Overview"], ["campaigns", "Campaigns"], ["adsets", "Ad sets & ads"], ["audiences", "Audiences"], ["creatives", "Creative library"], ["analytics", "Analytics"]]
    : [["overview", "Overview"], ["campaigns", "Campaigns"], ["adgroups", "Ad groups & keywords"], ["research", "Keyword research"], ["tracking", "Conversion tracking"], ["analytics", "Analytics"]];

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-bold tracking-tight">{name}</h1>
          <p className="mt-1 text-[15px] text-muted">Prepare campaigns freely. Launches, activations, budget increases and other changes to live campaigns go to Approvals first.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => sync.mutate(undefined)} loading={sync.isPending}>Sync performance</Button>
          {canWrite && <Button onClick={() => setCreating("ai")}><Sparkles className="size-4" aria-hidden /> AI draft</Button>}
          {canWrite && <Button variant="primary" onClick={() => setCreating("wizard")}><Plus className="size-4" aria-hidden /> Create campaign</Button>}
        </div>
      </div>
      {!accounts?.length && <Notice tone="warning" className="mb-4">No {name} account connected. <Link className="underline" href="/integrations">Connect one</Link> (or use a sandbox account) to launch campaigns.</Notice>}
      <Tabs value={tab} onChange={setTab} tabs={tabs.map(([value, label]) => ({ value, label }))} />
      <div className="mt-5 space-y-5">
        {(tab === "overview" || tab === "analytics") && (
          <>
            <div className="flex justify-end"><RangePicker value={range} onChange={setRange} /></div>
            <div className="grid grid-cols-2 overflow-hidden rounded-[var(--radius-panel)] border border-rule bg-surface sm:grid-cols-4 lg:grid-cols-8 [&>div]:border-b [&>div]:border-r [&>div]:border-rule">
              {[["Spend", formatMoney(insights?.totals.spend_minor ?? null, cur)], ["Impressions", formatNumber(insights?.totals.impressions ?? null)],
                ["Reach", formatNumber(insights?.totals.reach ?? null)], ["Clicks", formatNumber(insights?.totals.clicks ?? null)],
                ["CTR", insights?.totals.ctr != null ? `${(insights.totals.ctr * 100).toFixed(2)}%` : "—"], ["CPC", formatMoney(insights?.totals.cpc_minor ?? null, cur, 2)],
                ["Results", formatNumber(insights?.totals.results ?? null)], ["ROAS", insights?.totals.roas != null ? `${insights.totals.roas.toFixed(2)}×` : "—"]].map(([k, v]) => (
                <div key={k} className="px-4 py-3"><p className="text-xs text-muted">{k}</p><p className="text-lg font-bold tabular">{v}</p></div>
              ))}
            </div>
            {insights?.sources.includes("demo") && <Notice tone="warning">Includes demo data.</Notice>}
            <div className="grid gap-5 lg:grid-cols-[1.5fr_1fr]">
              <Panel title="Daily spend and results">
                <LineChart title="Daily spend" labels={(insights?.daily ?? []).map((d) => d.date)} format={(v) => formatMoney(v, cur)}
                  series={[{ key: "spend", label: "Spend", color: SERIES_COLORS[0], values: (insights?.daily ?? []).map((d) => d.spend_minor) }]} />
              </Panel>
              <Panel title="Recommendations" description="From synced performance. Changes they suggest still go through approval.">
                {recs?.recommendations.length ? (
                  <ul className="space-y-3">{recs.recommendations.map((r, i) => (
                    <li key={i} className="text-[13px]"><p className="font-medium">{r.title}</p><p className="text-muted">{r.action}</p>
                      {r.requires_approval && <span className="text-xs text-marigold-deep">Acting on this needs approval</span>}</li>
                  ))}</ul>
                ) : <p className="text-[13px] text-muted">{recs?.note ?? "No recommendations right now."}</p>}
              </Panel>
            </div>
          </>
        )}
        {(tab === "overview" || tab === "campaigns") && (
          <Panel title="Campaigns">
            {campaigns?.length ? (
              <Table head={["Campaign", "Status", "Objective", "Daily budget", "Spend (30d)", "Results", "CPA"]}>
                {campaigns.map((c) => (
                  <tr key={c.id} className="cursor-pointer hover:bg-paper" onClick={() => setOpen(c.id)}>
                    <td><span className="font-medium">{c.name}</span> {c.created_by_ai && <Tag tone="ai">AI</Tag>}</td>
                    <td><StatusBadge status={c.status} /></td>
                    <td>{pretty(c.objective)}</td>
                    <td className="tabular">{formatMoney(c.daily_budget_minor, c.currency)}</td>
                    <td className="tabular">{formatMoney(c.last_30_days?.spend_minor ?? null, c.currency)}</td>
                    <td className="tabular">{formatNumber(c.last_30_days?.results ?? null)}</td>
                    <td className="tabular">{formatMoney(c.last_30_days?.cpa_minor ?? null, c.currency)}</td>
                  </tr>
                ))}
              </Table>
            ) : <Empty title="No campaigns yet" body="Create one step by step, or let the AI draft it from your brand profile." />}
          </Panel>
        )}
        {(tab === "adsets" || tab === "adgroups") && (
          <Panel title={platform === "meta" ? "Ad sets and ads" : "Ad groups and keywords"}>
            {campaigns?.length ? (
              <ul className="space-y-4">
                {campaigns.map((c) => (
                  <li key={c.id}>
                    <button className="font-medium hover:underline" onClick={() => setOpen(c.id)}>{c.name}</button>
                    {platform === "meta" ? (
                      <p className="text-[13px] text-muted">Ad set: ages {c.config.audience?.age_min}–{c.config.audience?.age_max}, {(c.config.geo?.countries ?? []).join(", ")}, {c.config.placements?.automatic ? "automatic placements" : (c.config.placements?.publisher_platforms ?? []).join(", ")} · Ad: “{c.config.copy?.headline ?? "—"}”</p>
                    ) : (
                      <ul className="mt-1 space-y-1 text-[13px] text-muted">
                        {(c.config.ad_groups ?? []).map((g: { name: string; keywords: { text: string; match_type: string }[] }) => (
                          <li key={g.name}><span className="text-ink">{g.name}:</span> {g.keywords.map((k) => (k.match_type === "EXACT" ? `[${k.text}]` : k.match_type === "PHRASE" ? `"${k.text}"` : k.text)).join(", ")}</li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-muted">No campaigns yet.</p>}
          </Panel>
        )}
        {tab === "audiences" && (
          <Panel title="Audiences" description="Targeting used by your campaigns. Custom audiences from Meta can be referenced by id in a campaign's audience.">
            <Table head={["Campaign", "Ages", "Gender", "Interests", "Locations"]}>
              {(campaigns ?? []).map((c) => (
                <tr key={c.id}><td>{c.name}</td><td className="tabular">{c.config.audience?.age_min}–{c.config.audience?.age_max}</td>
                  <td>{c.config.audience?.genders?.length ? (c.config.audience.genders[0] === 1 ? "Men" : "Women") : "All"}</td>
                  <td>{(c.config.audience?.interests ?? []).map((i: { name: string }) => i.name).join(", ") || "—"}</td>
                  <td>{[...(c.config.geo?.countries ?? []), ...(c.config.geo?.cities ?? []).map((x: { name: string }) => x.name)].join(", ")}</td></tr>
              ))}
            </Table>
          </Panel>
        )}
        {tab === "creatives" && <CreativeLibrary />}
        {tab === "research" && <KeywordResearch />}
        {tab === "tracking" && <ConversionTracking />}
        {tab === "analytics" && insights && insights.campaigns.length > 0 && (
          <Panel title="By campaign">
            <Table head={["Campaign", "Spend", "Clicks", "CTR", "CPC", "Results", "CPA", "ROAS"]}>
              {insights.campaigns.map((c) => (
                <tr key={c.campaign_id}><td>{c.name}</td><td className="tabular">{formatMoney(c.spend_minor, cur)}</td><td className="tabular">{formatNumber(c.clicks)}</td>
                  <td className="tabular">{c.ctr != null ? `${(c.ctr * 100).toFixed(2)}%` : "—"}</td><td className="tabular">{formatMoney(c.cpc_minor, cur, 2)}</td>
                  <td className="tabular">{formatNumber(c.results)}</td><td className="tabular">{formatMoney(c.cpa_minor, cur)}</td><td className="tabular">{c.roas != null ? `${c.roas.toFixed(2)}×` : "—"}</td></tr>
              ))}
            </Table>
          </Panel>
        )}
      </div>
      <Drawer open={creating !== null} onClose={() => setCreating(null)} title={creating === "ai" ? "Draft with AI" : "Create campaign"} width="max-w-3xl">
        {creating === "wizard" && <Wizard platform={platform} accounts={accounts ?? []} onDone={(id) => { setCreating(null); setOpen(id); }} />}
        {creating === "ai" && <AiDraft platform={platform} onDone={(id) => { setCreating(null); setOpen(id); }} />}
      </Drawer>
      {open && <CampaignDetail platform={platform} id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function CreativeLibrary() {
  const { data } = useApiQuery<{ id: string; url: string; source: string; prompt: string | null }[]>("/media", { kind: "image" });
  return (
    <Panel title="Creative library" description="Images uploaded or generated in this workspace.">
      {data?.length ? (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {data.map((m) => (
            <li key={m.id} className="space-y-1">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={m.url} alt={m.prompt ?? ""} className="aspect-square w-full rounded-md border border-rule object-cover" />
              <p className="line-clamp-1 text-[11px] text-muted">{m.source === "upload" ? "Uploaded" : m.source === "ai" ? "AI generated" : "Offline placeholder"}</p>
            </li>
          ))}
        </ul>
      ) : <Empty title="No creatives yet" body="Generate images in the Content studio." action={<Link className="underline" href="/content-studio">Open Content studio</Link>} />}
    </Panel>
  );
}

function KeywordResearch() {
  const [seed, setSeed] = useState("");
  const [query, setQuery] = useState<string | null>(null);
  const { data, error, isFetching } = useApiQuery<{ source: string; note?: string; ideas: { text: string; intent: string; avg_monthly_searches: number | null; competition: string | null; low_bid_minor: number | null; high_bid_minor: number | null }[] }>(
    query ? "/ads/google/keywords" : null, { seed: query ?? "" });
  return (
    <Panel title="Keyword research" description="Volumes and bid ranges come from Google's Keyword Planner on your connected account.">
      <form className="mb-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); setQuery(seed); }}>
        <Input value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="thali restaurant, coastal food" />
        <Button variant="primary" loading={isFetching}>Find keywords</Button>
      </form>
      {error && <Notice tone="error">{errorMessage(error)}</Notice>}
      {data?.note && <Notice tone="warning" className="mb-3">{data.note}</Notice>}
      {data && (
        <Table head={["Keyword", "Intent (estimated)", "Monthly searches", "Competition", "Top-of-page bid"]}>
          {data.ideas.map((i) => (
            <tr key={i.text}><td>{i.text}</td><td className="capitalize">{i.intent}</td><td className="tabular">{formatNumber(i.avg_monthly_searches)}</td>
              <td className="capitalize">{i.competition?.toLowerCase() ?? "—"}</td>
              <td className="tabular">{i.low_bid_minor != null ? `${formatMoney(i.low_bid_minor, "INR", 2)}–${formatMoney(i.high_bid_minor, "INR", 2)}` : "—"}</td></tr>
          ))}
        </Table>
      )}
    </Panel>
  );
}

function ConversionTracking() {
  const { data, error } = useApiQuery<{ source: string; actions: { name: string; status: string; category: string }[]; issues: string[]; clicks_30d?: number; conversions_30d?: number }>("/ads/google/conversion-tracking");
  return (
    <Panel title="Conversion tracking" description="Checks that Google Ads can see the actions you care about.">
      {error && <Notice tone="error">{errorMessage(error)}</Notice>}
      {data?.issues.map((i) => <Notice key={i} tone="warning" className="mb-2">{i}</Notice>)}
      {data && !data.issues.length && <Notice tone="success">Conversion tracking looks healthy.</Notice>}
      {data?.actions.length ? (
        <Table head={["Conversion action", "Category", "Status"]} className="mt-3">
          {data.actions.map((a) => <tr key={a.name}><td>{a.name}</td><td>{a.category}</td><td>{a.status}</td></tr>)}
        </Table>
      ) : null}
    </Panel>
  );
}
