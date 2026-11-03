"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, Field, Input, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";

function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (done) {
    return (
      <div className="space-y-4">
        <Notice tone="success">Password changed. Every other session was signed out.</Notice>
        <Link href="/login" className="font-medium underline">Sign in</Link>
      </div>
    );
  }
  return (
    <form className="space-y-5" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      try { await api.post("/auth/reset-password", { token, password }); setDone(true); } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
    }}>
      <h1 className="text-2xl font-bold tracking-tight">Choose a new password</h1>
      {error && <Notice tone="error">{error}</Notice>}
      <Field label="New password" hint="At least 10 characters with upper- and lower-case letters and a number.">
        <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" required minLength={10} />
      </Field>
      <Button variant="primary" className="w-full" loading={busy} disabled={!token}>Change password</Button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return <Suspense><ResetForm /></Suspense>;
}
