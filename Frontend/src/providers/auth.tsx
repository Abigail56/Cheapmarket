"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, setSignedOutHandler } from "@/lib/api";
import { tokenStore } from "@/lib/storage";
import type { AuthResponse, TokenPair, User } from "@/lib/types";

interface AuthState {
  user: User | null;
  ready: boolean; // false until we know whether someone is signed in
  login: (email: string, password: string) => Promise<User>;
  register: (data: { full_name: string; email: string; phone?: string; password: string }) => Promise<User>;
  googleSignIn: (idToken: string) => Promise<User>;
  logout: () => Promise<void>;
  setUser: (u: User) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

// Listeners (the cart) that must react when someone signs in or out
type Listener = (user: User | null) => void | Promise<void>;
const listeners = new Set<Listener>();
export function onAuthChange(fn: Listener) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const changeUser = useCallback(async (u: User | null) => {
    setUserState(u);
    await Promise.all([...listeners].map((fn) => fn(u)));
  }, []);

  useEffect(() => {
    setSignedOutHandler(() => {
      void changeUser(null);
    });
    let cancelled = false;
    (async () => {
      try {
        if (tokenStore.get()) {
          const me = await api<User>("/users/me");
          if (!cancelled) setUserState(me);
        }
      } catch {
        /* expired or offline: treated as signed out */
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
      setSignedOutHandler(null);
    };
  }, [changeUser]);

  const signIn = useCallback(
    async (tokens: TokenPair, u?: User) => {
      tokenStore.set({ access: tokens.access_token, refresh: tokens.refresh_token });
      const me = u ?? (await api<User>("/users/me"));
      await changeUser(me);
      return me;
    },
    [changeUser],
  );

  const value = useMemo<AuthState>(
    () => ({
      user,
      ready,
      login: async (email, password) =>
        signIn(await api<TokenPair>("/auth/login", { method: "POST", body: { email, password }, auth: false })),
      register: async (data) => {
        const res = await api<AuthResponse>("/auth/register", { method: "POST", body: data, auth: false });
        return signIn(res, res.user);
      },
      googleSignIn: async (idToken) => {
        const res = await api<AuthResponse>("/auth/google", {
          method: "POST",
          body: { id_token: idToken, create_account: true },
          auth: false,
        });
        return signIn(res, res.user);
      },
      logout: async () => {
        const tokens = tokenStore.get();
        if (tokens) {
          await api("/auth/logout", { method: "POST", body: { refresh_token: tokens.refresh } }).catch(() => {});
        }
        tokenStore.set(null);
        await changeUser(null);
      },
      setUser: (u) => setUserState(u),
    }),
    [user, ready, signIn, changeUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
