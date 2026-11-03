"use client";

import { createApiClient, type Session } from "@marketingos/api-client";
import { useAuth } from "./store";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

let refreshing: Promise<boolean> | null = null;

async function refresh(): Promise<boolean> {
  const token = useAuth.getState().refreshToken;
  if (!token) return false;
  refreshing ??= fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: token }),
  })
    .then(async (res) => {
      if (!res.ok) return false;
      useAuth.getState().setSession((await res.json()) as Session);
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export const api = createApiClient({
  baseUrl: API_URL,
  getAccessToken: () => useAuth.getState().accessToken,
  getWorkspaceId: () => useAuth.getState().workspaceId,
  refresh,
  onUnauthorized: () => {
    useAuth.getState().clear();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) window.location.href = "/login";
  },
});

export async function downloadFile(path: string, filename: string, method = "GET") {
  const blob = await api.blob(path, method);
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(href);
}
