"use client";

import { Suspense } from "react";
import { AdsManager } from "@/components/ads-manager";

export default function Page() {
  return <Suspense><AdsManager platform="google" /></Suspense>;
}
