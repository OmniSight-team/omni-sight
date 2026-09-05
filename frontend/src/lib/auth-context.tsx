"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { type CurrentUser, getCurrentUser, getToken, logout as apiLogout } from "@/lib/api-client";

interface AuthContextValue {
  user: CurrentUser | null;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/sign-in");
      return;
    }
    getCurrentUser()
      .then(setUser)
      .catch(() => {
        // A 401 here is already handled by the API client (clears the
        // token and redirects to /sign-in).
      })
      .finally(() => setReady(true));
  }, [router]);

  async function logout() {
    await apiLogout();
    router.replace("/sign-in");
  }

  if (!ready) return null;

  return <AuthContext.Provider value={{ user, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
