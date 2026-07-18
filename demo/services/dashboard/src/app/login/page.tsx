"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Shield, AlertCircle } from "lucide-react"
import { useAuth } from "@/lib/auth"

export default function LoginPage() {
  const { login } = useAuth()
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError("")
    setLoading(true)
    await new Promise((r) => setTimeout(r, 280))
    const ok = login(email, password)
    if (ok) {
      router.push("/")
    } else {
      setError("Invalid credentials. Check the demo accounts below.")
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 px-4">
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center size-12 rounded-xl bg-primary/10 border border-primary/20 mb-1">
            <Shield className="size-6 text-primary" />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">OmniSight</h1>
          <p className="text-sm text-muted-foreground">Semantic Video Intelligence Platform</p>
        </div>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Sign In</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-sm font-medium">Email</label>
                <Input
                  type="email"
                  placeholder="you@omni.local"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">Password</label>
                <Input
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
              </div>
              {error && (
                <div className="flex items-center gap-2 text-destructive text-sm bg-destructive/10 border border-destructive/20 rounded-lg px-3 py-2">
                  <AlertCircle className="size-4 shrink-0" />
                  {error}
                </div>
              )}
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "Signing in…" : "Sign In"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <div className="rounded-lg border border-border bg-muted/40 px-4 py-3 text-xs text-muted-foreground space-y-1.5">
          <p className="font-medium text-foreground">Demo accounts</p>
          <p>
            <span className="font-mono text-foreground">operator@omni.local</span>
            <span className="text-muted-foreground"> / demo</span>
            <span className="ml-2 text-[10px] uppercase tracking-wider text-muted-foreground/60">Operator</span>
          </p>
          <p>
            <span className="font-mono text-foreground">admin@omni.local</span>
            <span className="text-muted-foreground"> / demo</span>
            <span className="ml-2 text-[10px] uppercase tracking-wider text-muted-foreground/60">Admin</span>
          </p>
        </div>
      </div>
    </div>
  )
}
