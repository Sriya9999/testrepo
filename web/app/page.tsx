"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth, useHydrated } from "@/lib/store";

export default function Home() {
  const accessToken = useAuth((s) => s.accessToken);
  const hydrated = useHydrated();
  const router = useRouter();
  useEffect(() => {
    if (hydrated) router.replace(accessToken ? "/dashboard" : "/login");
  }, [hydrated, accessToken, router]);
  return null;
}
