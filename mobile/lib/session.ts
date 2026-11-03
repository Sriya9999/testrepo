import type { Session, User } from "@marketingos/api-client";
import * as SecureStore from "expo-secure-store";
import { create } from "zustand";

const KEY = "marketingos.session";

interface SessionState {
  ready: boolean;
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
  workspaceId: string | null;
  load: () => Promise<void>;
  setSession: (s: Session) => void;
  setUser: (u: User) => void;
  setWorkspace: (id: string) => void;
  clear: () => void;
}

/** Tokens live in the device keychain / keystore (expo-secure-store), never in plain storage. */
export const useSession = create<SessionState>((set, get) => {
  const persist = () => {
    const { accessToken, refreshToken, user, workspaceId } = get();
    SecureStore.setItemAsync(KEY, JSON.stringify({ accessToken, refreshToken, user, workspaceId })).catch(() => undefined);
  };
  return {
    ready: false,
    accessToken: null,
    refreshToken: null,
    user: null,
    workspaceId: null,
    load: async () => {
      try {
        const raw = await SecureStore.getItemAsync(KEY);
        if (raw) set(JSON.parse(raw));
      } finally {
        set({ ready: true });
      }
    },
    setSession: (s) => {
      const current = get().workspaceId;
      const keep = s.user.workspaces.some((w) => w.id === current);
      set({ accessToken: s.access_token, refreshToken: s.refresh_token, user: s.user, workspaceId: keep ? current : s.user.workspaces[0]?.id ?? null });
      persist();
    },
    setUser: (u) => { set({ user: u }); persist(); },
    setWorkspace: (id) => { set({ workspaceId: id }); persist(); },
    clear: () => { set({ accessToken: null, refreshToken: null, user: null, workspaceId: null }); SecureStore.deleteItemAsync(KEY).catch(() => undefined); },
  };
});
