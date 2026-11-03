"use client";

import type { JobStatus, Query, WorkspaceDetail } from "@marketingos/api-client";
import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import { api } from "./api";
import { useAuth } from "./store";

export function useApiQuery<T>(path: string | null, query?: Query, options?: Partial<UseQueryOptions<T>>) {
  const workspaceId = useAuth((s) => s.workspaceId);
  return useQuery<T>({
    queryKey: ["api", workspaceId, path, query ?? null],
    queryFn: () => api.get<T>(path as string, query),
    enabled: Boolean(path && workspaceId) && (options?.enabled ?? true),
    ...options,
  } as UseQueryOptions<T>);
}

/** Run a mutation, then refresh every cached query whose path starts with one of `invalidate`. */
export function useApiMutation<TIn, TOut = unknown>(fn: (input: TIn) => Promise<TOut>, invalidate: string[] = []) {
  const qc = useQueryClient();
  return useMutation<TOut, Error, TIn>({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({
        predicate: (q) => q.queryKey[0] === "api" && invalidate.some((p) => String(q.queryKey[2] ?? "").startsWith(p)),
      });
    },
  });
}

export function useJob(jobId: string | null | undefined, onDone?: (job: JobStatus) => void) {
  const qc = useQueryClient();
  return useQuery<JobStatus>({
    queryKey: ["job", jobId],
    queryFn: async () => {
      const job = await api.get<JobStatus>(`/jobs/${jobId}`);
      if (job.status === "succeeded" || job.status === "failed") {
        onDone?.(job);
        qc.invalidateQueries({ queryKey: ["api"] });
      }
      return job;
    },
    enabled: Boolean(jobId),
    refetchInterval: (q) => (q.state.data && ["succeeded", "failed"].includes(q.state.data.status) ? false : 1200),
  });
}

export function useWorkspace() {
  const workspaceId = useAuth((s) => s.workspaceId);
  return useQuery<WorkspaceDetail>({
    queryKey: ["workspace", workspaceId],
    queryFn: () => api.get<WorkspaceDetail>(`/workspaces/${workspaceId}`),
    enabled: Boolean(workspaceId),
  });
}

export function useCan(permission: string): boolean {
  const { data } = useWorkspace();
  return Boolean(data?.permissions.includes(permission));
}

export function errorMessage(err: unknown): string {
  if (!err) return "";
  if (err instanceof Error) return err.message;
  return String(err);
}

/** Query a specific workspace (e.g. an agency viewing one client) without switching the active workspace. */
export function useWorkspaceQuery<T>(workspaceId: string | null | undefined, path: string, query?: Query) {
  return useQuery<T>({
    queryKey: ["api", workspaceId, path, query ?? null],
    queryFn: () => api.get<T>(path, query, workspaceId),
    enabled: Boolean(workspaceId),
  });
}
