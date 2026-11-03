"use client";

import type { Session } from "@marketingos/api-client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, Field, Input, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";
import { useAuth } from "@/lib/store";

type LoginResult = Session | { mfa_required: true; mfa_token: string };

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const setSession = useAuth((s) => s.setSession);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const finish = (s: Session) => {
    setSession(s);
    router.replace(s.user.onboarding_completed ? params.get("next") || "/dashboard" : "/onboarding");
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mfaToken) {
        finish(await api.post<Session>("/auth/login/mfa", { mfa_token: mfaToken, code }));
      } else {
        const r = await api.post<LoginResult>("/auth/login", { email, password });
        if ("mfa_required" in r) setMfaToken(r.mfa_token);
        else finish(r);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{mfaToken ? "Enter your code" : "Sign in"}</h1>
        <p className="mt-1 text-muted">{mfaToken ? "Open your authenticator app and enter the 6-digit code." : "Welcome back."}</p>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {mfaToken ? (
        <Field label="Authentication code">
          <Input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" autoFocus required />
        </Field>
      ) : (
        <>
          <Field label="Email">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required autoFocus />
          </Field>
          <Field label="Password">
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          </Field>
        </>
      )}
      <Button variant="primary" className="w-full" loading={busy}>{mfaToken ? "Verify" : "Sign in"}</Button>
      {!mfaToken && (
        <div className="flex justify-between text-[13px]">
          <Link href="/forgot-password" className="text-muted underline-offset-2 hover:underline">Forgot password?</Link>
          <Link href="/register" className="font-medium underline-offset-2 hover:underline">Create an account</Link>
        </div>
      )}
      <p className="text-xs text-faint">
        By signing in you agree to the <a href="/terms" className="underline">Terms</a> and <a href="/privacy" className="underline">Privacy policy</a>.
      </p>
    </form>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
