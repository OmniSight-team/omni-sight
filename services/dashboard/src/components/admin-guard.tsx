"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"
import { useAuth } from "@/lib/auth"

export function AdminGuard({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (user !== null && user.role !== "admin") {
      router.replace("/")
    }
  }, [user, router])

  if (!user || user.role !== "admin") return null

  return <>{children}</>
}
