"use client";

import type { Session } from "@marketingos/api-client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, cn, Field, Input, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";
import { useAuth } from "@/lib/store";

export default function RegisterPage() {
  const router = useRouter();
  const setSession = useAuth((s) => s.setSession);
  const [form, setForm] = useState({ full_name: "", email: "", password: "", organization_name: "", account_type: "business" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setSession(await api.post<Session>("/auth/register", form));
      router.replace("/onboarding");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Create your account</h1>
        <p className="mt-1 text-muted">14-day trial with 100 AI credits. No card needed.</p>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      <fieldset>
        <legend className="mb-1.5 text-[13px] font-medium text-ink-2">I'm setting this up for</legend>
        <div className="grid grid-cols-2 gap-2">
          {[["business", "My business"], ["agency", "My agency's clients"]].map(([v, l]) => (
            <label key={v} className={cn("cursor-pointer rounded-[var(--radius-control)] border px-3 py-2.5 text-sm",
              form.account_type === v ? "border-ink bg-surface font-semibold" : "border-rule-strong text-ink-2")}>
              <input type="radio" name="account_type" value={v} checked={form.account_type === v}
                onChange={() => setForm({ ...form, account_type: v })} className="sr-only" />
              {l}
            </label>
          ))}
        </div>
      </fieldset>
      <Field label="Your name"><Input value={form.full_name} onChange={set("full_name")} autoComplete="name" required /></Field>
      <Field label={form.account_type === "agency" ? "Agency name" : "Business name"}>
        <Input value={form.organization_name} onChange={set("organization_name")} required />
      </Field>
      <Field label="Work email"><Input type="email" value={form.email} onChange={set("email")} autoComplete="email" required /></Field>
      <Field label="Password" hint="At least 10 characters with upper- and lower-case letters and a number.">
        <Input type="password" value={form.password} onChange={set("password")} autoComplete="new-password" minLength={10} required />
      </Field>
      <Button variant="primary" className="w-full" loading={busy}>Create account</Button>
      <p className="text-[13px] text-muted">Already have an account? <Link href="/login" className="font-medium text-ink underline-offset-2 hover:underline">Sign in</Link></p>
    </form>
  );
}
