"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, Field, Input, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form className="space-y-5" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      try { await api.post("/auth/forgot-password", { email }); setSent(true); } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
    }}>
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Reset your password</h1>
        <p className="mt-1 text-muted">We'll email you a link that works for one hour.</p>
      </div>
      {sent && <Notice tone="success">If an account exists for {email}, a reset link is on its way.</Notice>}
      {error && <Notice tone="error">{error}</Notice>}
      <Field label="Email"><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus /></Field>
      <Button variant="primary" className="w-full" loading={busy}>Send reset link</Button>
      <Link href="/login" className="block text-[13px] text-muted hover:text-ink">Back to sign in</Link>
    </form>
  );
}
