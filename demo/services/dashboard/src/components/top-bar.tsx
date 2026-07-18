"use client"

import { useAuth } from "@/lib/auth"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { LogOut } from "lucide-react"
import { useRouter } from "next/navigation"

export function TopBar() {
  const { user, logout } = useAuth()
  const router = useRouter()

  function handleLogout() {
    logout()
    router.push("/login")
  }

  if (!user) return null

  return (
    <header className="h-11 shrink-0 flex items-center justify-end gap-3 px-4 border-b border-border bg-background/60 backdrop-blur-sm">
      <span className="text-sm text-muted-foreground">{user.name}</span>
      <Badge
        variant={user.role === "admin" ? "default" : "secondary"}
        className="text-[11px] px-2"
      >
        {user.role}
      </Badge>
      <Button
        variant="ghost"
        size="icon"
        className="size-7 text-muted-foreground hover:text-foreground"
        onClick={handleLogout}
        title="Sign out"
      >
        <LogOut className="size-3.5" />
      </Button>
    </header>
  )
}
