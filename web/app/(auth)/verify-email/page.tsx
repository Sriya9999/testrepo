"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Notice, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";
import { useAuth } from "@/lib/store";

function Verify() {
  const token = useSearchParams().get("token");
  const [state, setState] = useState<"working" | "done" | "error">("working");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!token) { setState("error"); setError("This link is missing its token."); return; }
    api.post("/auth/verify-email", { token })
      .then(async () => {
        setState("done");
        if (useAuth.getState().accessToken) useAuth.getState().setUser(await api.get("/users/me"));
      })
      .catch((e) => { setState("error"); setError(errorMessage(e)); });
  }, [token]);
  if (state === "working") return <Spinner label="Verifying your email" />;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Email verification</h1>
      {state === "done" ? <Notice tone="success">Your email is verified.</Notice> : <Notice tone="error">{error}</Notice>}
      <Link href="/dashboard" className="font-medium underline">Go to your dashboard</Link>
    </div>
  );
}

export default function VerifyEmailPage() {
  return <Suspense><Verify /></Suspense>;
}
