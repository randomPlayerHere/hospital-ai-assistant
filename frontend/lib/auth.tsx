"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  api,
  clearTokens,
  getRefreshToken,
  refreshTokens,
  setLogoutHandler,
  setTokens,
  unwrap,
  type Role,
} from "./api";

export type User = { id: string; email: string; full_name: string; role: Role; mfa_enabled: boolean };
export type LoginResult = { user?: User; mfa_required?: boolean; mfa_ticket?: string | null };

type AuthState = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<LoginResult>;
  verifyMfaLogin: (mfa_ticket: string, code: string) => Promise<User>;
  register: (body: RegisterBody) => Promise<User>;
  reloadMe: () => Promise<User>;
  logout: () => Promise<void>;
};
export type RegisterBody = {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  date_of_birth: string;
  phone?: string;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const loadMe = useCallback(async (): Promise<User> => {
    const me = unwrap(await api.GET("/api/auth/me"));
    const u: User = {
      id: me.id,
      email: me.email,
      full_name: me.full_name,
      role: me.role as Role,
      mfa_enabled: Boolean(me.mfa_enabled),
    };
    setUser(u);
    return u;
  }, []);

  useEffect(() => {
    setLogoutHandler(() => {
      clearTokens();
      setUser(null);
    });
    (async () => {
      try {
        if (getRefreshToken() && (await refreshTokens())) await loadMe();
      } catch {
        clearTokens();
      } finally {
        setLoading(false);
      }
    })();
    return () => setLogoutHandler(null);
  }, [loadMe]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      login: async (email, password) => {
        const pair = unwrap(await api.POST("/api/auth/login", { body: { email, password } }));
        if (pair.mfa_required) {
          return { mfa_required: true, mfa_ticket: pair.mfa_ticket };
        }
        setTokens(pair);
        const u = await loadMe();
        return { user: u, mfa_required: false };
      },
      verifyMfaLogin: async (mfa_ticket, code) => {
        const pair = unwrap(
          await api.POST("/api/auth/mfa/verify-login", { body: { mfa_ticket, code } }),
        );
        setTokens(pair);
        return loadMe();
      },
      register: async (body) => {
        setTokens(unwrap(await api.POST("/api/auth/register", { body })));
        return loadMe();
      },
      reloadMe: loadMe,
      logout: async () => {
        const refresh = getRefreshToken();
        if (refresh) await api.POST("/api/auth/logout", { body: { refresh_token: refresh } });
        clearTokens();
        setUser(null);
      },
    }),
    [user, loading, loadMe],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}
