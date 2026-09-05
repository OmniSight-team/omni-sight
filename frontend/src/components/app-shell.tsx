"use client";

import type { ReactNode } from "react";

import { useAuth } from "@/lib/auth-context";
import { Sidebar } from "@/components/sidebar";
import { TopBar } from "@/components/top-bar";

export function AppShell({ children }: { children: ReactNode }) {
  const { user } = useAuth();

  if (!user) return null;

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <TopBar />
      <div className="flex flex-1">
        <Sidebar />
        <div className="flex-1 bg-zinc-50 dark:bg-zinc-950">{children}</div>
      </div>
    </div>
  );
}
