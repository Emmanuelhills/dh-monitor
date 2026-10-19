"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { ApiError, api, setCsrfToken, setUnauthorizedHandler } from "./api";

interface Me {
  id: string;
  email: string;
  csrf_token: string;
}

interface AuthState {
  user: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export const PUBLIC_PATHS = ["/", "/login"];

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const accept = useCallback((me: Me | null) => {
    setUser(me);
    setCsrfToken(me?.csrf_token ?? null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      accept(null);
      if (!PUBLIC_PATHS.includes(window.location.pathname)) {
        router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
      }
    });
    api
      .get<Me>("/auth/me")
      .then(accept)
      .catch((err) => {
        if (!(err instanceof ApiError && err.status === 401)) console.error(err);
        accept(null);
      })
      .finally(() => setLoading(false));
    return () => setUnauthorizedHandler(null);
  }, [accept, router]);

  useEffect(() => {
    if (!loading && !user && !PUBLIC_PATHS.includes(pathname)) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [loading, user, pathname, router]);

  const login = useCallback(
    async (email: string, password: string) => {
      accept(await api.post<Me>("/auth/login", { email, password }));
    },
    [accept],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      accept(null);
      router.replace("/");
    }
  }, [accept, router]);

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
