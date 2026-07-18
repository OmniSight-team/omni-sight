"use client"

import { ThemeProvider } from "next-themes"
import { AuthProvider } from "@/lib/auth"
import { UploadProvider } from "@/lib/upload-store"

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" disableTransitionOnChange>
      <AuthProvider>
        <UploadProvider>{children}</UploadProvider>
      </AuthProvider>
    </ThemeProvider>
  )
}
