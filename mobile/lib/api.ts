import { createApiClient, type Query, type Session } from "@marketingos/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Constants from "expo-constants";
import { useSession } from "./session";

export const API_URL: string = process.env.EXPO_PUBLIC_API_URL ?? (Constants.expoConfig?.extra?.apiUrl as string) ?? "http://localhost:8000";

let refreshing: Promise<boolean> | null = null;
function refresh(): Promise<boolean> {
  const token = useSession.getState().refreshToken;
  if (!token) return Promise.resolve(false);
  refreshing ??= fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: token }),
  })
    .then(async (r) => { if (!r.ok) return false; useSession.getState().setSession((await r.json()) as Session); return true; })
    .catch(() => false)
    .finally(() => { refreshing = null; });
  return refreshing;
}

export const api = createApiClient({
  baseUrl: API_URL,
  getAccessToken: () => useSession.getState().accessToken,
  getWorkspaceId: () => useSession.getState().workspaceId,
  refresh,
  onUnauthorized: () => useSession.getState().clear(),
});

export function useApi<T>(path: string | null, query?: Query, refetchInterval?: number) {
  const workspaceId = useSession((s) => s.workspaceId);
  return useQuery<T>({
    queryKey: ["api", workspaceId, path, query ?? null],
    queryFn: () => api.get<T>(path as string, query),
    enabled: Boolean(path && workspaceId),
    refetchInterval,
  });
}

export function useAction<TIn, TOut = unknown>(fn: (input: TIn) => Promise<TOut>) {
  const qc = useQueryClient();
  return useMutation<TOut, Error, TIn>({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ["api"] }) });
}
