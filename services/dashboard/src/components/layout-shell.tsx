"use client"

import { useEffect } from "react"
import { usePathname, useRouter } from "next/navigation"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { useAuth } from "@/lib/auth"

export function LayoutShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const { user } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (pathname !== "/login" && !user) {
      router.replace("/login")
    }
  }, [pathname, user, router])

  if (pathname === "/login") {
    return <div className="flex-1 overflow-auto">{children}</div>
  }

  if (!user) return null

  return (
    <>
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <TopBar />
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </>
  )
}
