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
        {/* min-w-0: a flex child is at least as wide as its content by default, so
            one wide thing on a page (a strip of thumbnails, a table) would stretch
            the whole page sideways instead of scrolling inside itself. */}
        <div className="min-w-0 flex-1 bg-zinc-50 dark:bg-zinc-950">{children}</div>
      </div>
    </div>
  );
}
