"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/store";

export default function Home() {
  const { hydrated, accessToken } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (hydrated) router.replace(accessToken ? "/dashboard" : "/login");
  }, [hydrated, accessToken, router]);
  return null;
}
