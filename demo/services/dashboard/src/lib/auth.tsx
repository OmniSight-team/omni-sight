"use client"

import { createContext, useContext, useEffect, useState, type ReactNode } from "react"

export type Role = "operator" | "admin"

export type AuthUser = {
  name: string
  email: string
  role: Role
}

const SEED: Record<string, { name: string; role: Role; password: string }> = {
  "operator@omni.local": { name: "Sara Malik",  role: "operator", password: "demo" },
  "admin@omni.local":    { name: "Ahmad Tawil", role: "admin",    password: "demo" },
}

const STORAGE_KEY = "omni_user"

type AuthCtx = {
  user: AuthUser | null
  login: (email: string, password: string) => boolean
  logout: () => void
}

const AuthContext = createContext<AuthCtx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) setUser(JSON.parse(raw))
    } catch { /* ignore */ }
  }, [])

  function login(email: string, password: string): boolean {
    const seed = SEED[email.trim().toLowerCase()]
    if (!seed || seed.password !== password) return false
    const u: AuthUser = { name: seed.name, email: email.trim().toLowerCase(), role: seed.role }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(u))
    setUser(u)
    return true
  }

  function logout() {
    localStorage.removeItem(STORAGE_KEY)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
