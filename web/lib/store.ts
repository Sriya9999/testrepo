"use client";

import type { Session, User } from "@marketingos/api-client";
import { useEffect, useState } from "react";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
  workspaceId: string | null;
  setSession: (s: Session) => void;
  setUser: (u: User) => void;
  setWorkspace: (id: string) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      workspaceId: null,
      setSession: (s) => {
        const current = get().workspaceId;
        const keep = s.user.workspaces.some((w) => w.id === current);
        set({
          accessToken: s.access_token,
          refreshToken: s.refresh_token,
          user: s.user,
          workspaceId: keep ? current : s.user.workspaces[0]?.id ?? null,
        });
      },
      setUser: (u) => set({ user: u }),
      setWorkspace: (id) => set({ workspaceId: id }),
      clear: () => set({ accessToken: null, refreshToken: null, user: null, workspaceId: null }),
    }),
    {
      name: "marketingos-session",
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ accessToken: s.accessToken, refreshToken: s.refreshToken, user: s.user, workspaceId: s.workspaceId }),
    },
  ),
);

/** True once the saved session has been read from localStorage (always false during SSR). */
export function useHydrated(): boolean {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    const unsubscribe = useAuth.persist.onFinishHydration(() => setHydrated(true));
    setHydrated(useAuth.persist.hasHydrated());
    return unsubscribe;
  }, []);
  return hydrated;
}

interface UiState {
  websiteId: string | null;
  geoProjectId: string | null;
  setWebsite: (id: string | null) => void;
  setGeoProject: (id: string | null) => void;
}

/** Per-viewer UI choices (selected website / GEO project), remembered across visits. */
export const useUi = create<UiState>()(
  persist(
    (set) => ({
      websiteId: null,
      geoProjectId: null,
      setWebsite: (id) => set({ websiteId: id }),
      setGeoProject: (id) => set({ geoProjectId: id }),
    }),
    { name: "marketingos-ui", storage: createJSONStorage(() => localStorage) },
  ),
);
