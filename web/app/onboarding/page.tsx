"use client";

import { formatMoney, type User } from "@marketingos/api-client";
import { Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, cn, Field, Input, Notice, Select, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";
import { useAuth, useHydrated } from "@/lib/store";

const STEPS = [
  "About you", "Account type", "Business details", "Industry", "Website", "Instagram", "Ad accounts", "Brand identity", "Plan", "Finish",
] as const;
const INDUSTRIES = ["Restaurant & café", "Retail", "Healthcare & clinics", "D2C brand", "Education", "Real estate", "Fitness & wellness",
  "Beauty & salon", "Professional services", "Travel & hospitality", "Other"];
const OPTIONAL = new Set([4, 5, 6, 8]);

interface Plan { code: string; name: string; audience: string; price_minor: number | null; monthly_credits: number }

export default function OnboardingPage() {
  const router = useRouter();
  const { user, workspaceId, accessToken, setUser } = useAuth();
  const hydrated = useHydrated();
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [connected, setConnected] = useState<Record<string, string>>({});
  const [form, setForm] = useState({
    full_name: "", workspace_name: "", timezone: "Asia/Kolkata", currency: "INR", industry: "", website: "", location: "",
    brand_name: "", colors: "#172033, #E8A317", voice: "", target_customers: "", products: "", ctas: "", prohibited: "",
  });

  useEffect(() => {
    if (hydrated && !accessToken) router.replace("/login");
    if (user) {
      setForm((f) => ({ ...f, full_name: f.full_name || user.full_name, workspace_name: f.workspace_name || user.workspaces[0]?.name || "",
        brand_name: f.brand_name || user.workspaces[0]?.name || "" }));
      const saved = Number((user.onboarding_state as { step?: number }).step ?? 0);
      if (saved) setStep(saved);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated, accessToken, user?.id]);

  useEffect(() => { api.get<Plan[]>("/billing/plans").then(setPlans).catch(() => undefined); }, []);

  if (!user || !workspaceId) return null;
  const isAgency = user.workspaces.find((w) => w.id === workspaceId)?.kind === "agency";
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: e.target.value });

  const save = async (next: number, completed = false) => {
    const u = await api.post<User>("/users/me/onboarding", { state: { step: next }, completed });
    setUser(u);
  };

  const connect = async (provider: string, mode: "live" | "sandbox") => {
    setError("");
    try {
      const r = await api.post<{ authorize_url?: string }>(`/integrations/${provider}/connect`, { mode });
      if (r.authorize_url) {
        await save(step);
        window.location.href = r.authorize_url;
        return;
      }
      setConnected({ ...connected, [provider]: mode });
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const next = async () => {
    setError("");
    setBusy(true);
    try {
      if (step === 0) await api.patch("/users/me", { full_name: form.full_name });
      if (step === 2 || step === 3) {
        await api.patch(`/workspaces/${workspaceId}`, { name: form.workspace_name, timezone: form.timezone, currency: form.currency,
          industry: form.industry || undefined });
      }
      if (step === 4 && form.website) await api.post("/seo/websites", { domain: form.website, target_location: form.location || null, target_country: "IN" });
      if (step === 7) {
        const brands = await api.get<{ id: string }[]>("/brands");
        const body = {
          name: form.brand_name, industry: form.industry, website_url: form.website ? `https://${form.website.replace(/^https?:\/\//, "")}` : null,
          colors: form.colors.split(",").map((c) => c.trim()).filter((c) => /^#[0-9a-f]{6}$/i.test(c)),
          voice: form.voice, target_customers: form.target_customers,
          products: form.products.split("\n").map((p) => p.trim()).filter(Boolean).map((name) => ({ name, description: "" })),
          approved_ctas: form.ctas.split(",").map((c) => c.trim()).filter(Boolean),
          prohibited_claims: form.prohibited.split(",").map((c) => c.trim()).filter(Boolean),
          locations: form.location ? [form.location] : [], is_default: true,
        };
        if (brands[0]) await api.patch(`/brands/${brands[0].id}`, body);
        else await api.post("/brands", body);
      }
      if (step === STEPS.length - 1) {
        await save(step, true);
        router.replace("/dashboard");
        return;
      }
      await save(step + 1);
      setStep(step + 1);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto grid min-h-screen max-w-5xl gap-10 px-4 py-10 md:grid-cols-[220px_1fr]">
      <aside>
        <div className="mb-6 flex items-center gap-2">
          <span className="grid size-7 place-items-center rounded-md bg-marigold text-sm font-black">M</span>
          <span className="font-bold">Set up MarketingOS</span>
        </div>
        <ol className="space-y-1">
          {STEPS.map((s, i) => (
            <li key={s} className={cn("flex items-center gap-2 rounded px-2 py-1 text-[13px]", i === step ? "bg-surface font-semibold" : i < step ? "text-ink-2" : "text-faint")}>
              <span className={cn("grid size-5 place-items-center rounded-full text-[11px]", i < step ? "bg-leaf text-white" : i === step ? "bg-ink text-white" : "bg-sunk")}>
                {i < step ? <Check className="size-3" /> : i + 1}
              </span>
              {s}{OPTIONAL.has(i) && <span className="text-[11px] font-normal text-faint">optional</span>}
            </li>
          ))}
        </ol>
      </aside>
      <section className="max-w-xl">
        <h1 className="text-[26px] font-bold tracking-tight">{STEPS[step]}</h1>
        {error && <Notice tone="error" className="mt-4">{error}</Notice>}
        <div className="mt-6 space-y-5">
          {step === 0 && <Field label="Your name"><Input value={form.full_name} onChange={set("full_name")} /></Field>}
          {step === 1 && (
            <p className="text-ink-2">
              {isAgency ? "You're set up as an agency. Each client gets an isolated workspace with its own brand, integrations, approvals and credits."
                : "You're set up as a business. You can invite your team and, later, an agency to help."}
            </p>
          )}
          {step === 2 && (
            <>
              <Field label={isAgency ? "Agency name" : "Business name"}><Input value={form.workspace_name} onChange={set("workspace_name")} /></Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Time zone"><Select value={form.timezone} onChange={set("timezone")} options={["Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Europe/London", "America/New_York"].map((v) => ({ value: v, label: v }))} /></Field>
                <Field label="Currency"><Select value={form.currency} onChange={set("currency")} options={["INR", "USD", "AED", "SGD", "GBP"].map((v) => ({ value: v, label: v }))} /></Field>
              </div>
            </>
          )}
          {step === 3 && (
            <div className="flex flex-wrap gap-2">
              {INDUSTRIES.map((i) => (
                <button key={i} type="button" onClick={() => setForm({ ...form, industry: i })}
                  className={cn("rounded-full border px-3 py-1.5 text-[13px]", form.industry === i ? "border-ink bg-ink text-white" : "border-rule-strong bg-surface")}>
                  {i}
                </button>
              ))}
            </div>
          )}
          {step === 4 && (
            <>
              <Field label="Website" hint="We'll use it for SEO audits and to ground AI content. You can add more sites later.">
                <Input value={form.website} onChange={set("website")} placeholder="yourbusiness.in" />
              </Field>
              <Field label="City or area you serve"><Input value={form.location} onChange={set("location")} placeholder="Pune" /></Field>
            </>
          )}
          {(step === 5 || step === 6) && (
            <div className="space-y-3">
              <p className="text-ink-2">
                {step === 5 ? "Connect an Instagram Professional account to schedule and publish posts." : "Connect ad accounts so agents can prepare campaigns for your approval."}
                {" "}A sandbox connection lets you try the full workflow without touching a real account.
              </p>
              {(step === 5 ? [["instagram", "Instagram"]] : [["meta", "Meta Ads"], ["google_ads", "Google Ads"]]).map(([p, label]) => (
                <div key={p} className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-panel)] border border-rule bg-surface px-4 py-3">
                  <span className="font-medium">{label}</span>
                  {connected[p] ? <span className="text-[13px] text-leaf">Connected ({connected[p]})</span> : (
                    <span className="flex gap-2">
                      <Button size="sm" variant="primary" onClick={() => connect(p, "live")}>Connect</Button>
                      <Button size="sm" onClick={() => connect(p, "sandbox")}>Use sandbox</Button>
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
          {step === 7 && (
            <>
              <p className="text-ink-2">Agents read this before writing anything, so drafts sound like you.</p>
              <Field label="Brand name"><Input value={form.brand_name} onChange={set("brand_name")} /></Field>
              <Field label="Brand colours" hint="Hex values, separated by commas."><Input value={form.colors} onChange={set("colors")} /></Field>
              <Field label="Voice" hint="A few words: warm, playful, premium…"><Input value={form.voice} onChange={set("voice")} /></Field>
              <Field label="Who you sell to"><Input value={form.target_customers} onChange={set("target_customers")} placeholder="Families in Pune who eat out on weekends" /></Field>
              <Field label="Products or services" hint="One per line."><Textarea rows={3} value={form.products} onChange={set("products")} /></Field>
              <Field label="Calls to action you use" hint="Comma separated, e.g. Book a table, Order now"><Input value={form.ctas} onChange={set("ctas")} /></Field>
              <Field label="Claims to never make" hint="Comma separated. Drafts containing these are blocked from approval."><Input value={form.prohibited} onChange={set("prohibited")} /></Field>
            </>
          )}
          {step === 8 && (
            <div className="grid gap-2 sm:grid-cols-2">
              {plans.map((p) => (
                <div key={p.code} className="rounded-[var(--radius-panel)] border border-rule bg-surface p-4">
                  <p className="font-semibold">{p.name}</p>
                  <p className="text-xs text-muted">{p.audience}</p>
                  <p className="mt-2 text-lg font-bold tabular">{p.price_minor === null ? "Custom" : `${formatMoney(p.price_minor)}/mo`}</p>
                  <p className="text-xs text-muted">{p.monthly_credits ? `${p.monthly_credits.toLocaleString("en-IN")} AI credits a month` : "Talk to us"}</p>
                </div>
              ))}
              <p className="text-[13px] text-muted sm:col-span-2">You're on a 14-day trial. Choose a plan any time from Billing.</p>
            </div>
          )}
          {step === 9 && (
            <div className="space-y-3 text-ink-2">
              <p>You're ready. A good first step: ask the AI assistant for a month of content and a campaign. Everything it drafts waits in Approvals until you release it.</p>
            </div>
          )}
        </div>
        <div className="mt-8 flex items-center gap-2">
          {step > 0 && <Button variant="ghost" onClick={() => setStep(step - 1)}>Back</Button>}
          <Button variant="primary" loading={busy} onClick={next}>{step === STEPS.length - 1 ? "Open my dashboard" : "Continue"}</Button>
          {OPTIONAL.has(step) && <Button variant="ghost" onClick={async () => { await save(step + 1); setStep(step + 1); }}>Skip for now</Button>}
        </div>
      </section>
    </div>
  );
}
