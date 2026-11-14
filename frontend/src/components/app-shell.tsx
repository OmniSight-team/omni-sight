"use client";

import type { ReactNode } from "react";

import { useAuth } from "@/lib/auth-context";
import { KeyboardShortcuts } from "@/components/keyboard-shortcuts";
import { Sidebar } from "@/components/sidebar";
import { TopBar } from "@/components/top-bar";

// The frame around every signed-in screen, in the "Night shift" look (frontend redesign). Screens
// move into the look one at a time; one not redesigned yet still draws its own zinc colours here.
export function AppShell({ children }: { children: ReactNode }) {
  const { user } = useAuth();

  if (!user) return null;

  return (
    <div className="flex min-h-full flex-1 flex-col bg-ns-ground font-console text-ns-text">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-ns-accent px-3 py-2 font-semibold text-ns-accent-ink focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to main content
      </a>
      <TopBar />
      <div className="flex flex-1">
        <Sidebar />
        {/* min-w-0: a flex child is at least as wide as its content by default, so
            one wide thing on a page (a strip of thumbnails, a table) would stretch
            the whole page sideways instead of scrolling inside itself. */}
        {/* Zinc until every screen is redesigned: a screen not moved yet still follows the
            computer's light or dark setting; a redesigned one paints its own graphite ground. */}
        <div id="main" tabIndex={-1} className="min-w-0 flex-1 bg-zinc-50 outline-none dark:bg-zinc-950">
          {children}
        </div>
      </div>
      <KeyboardShortcuts />
    </div>
  );
}
