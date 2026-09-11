"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { getNavRoutes, type NavRoute } from "@/lib/api-client";

// Only the dashboard has a real page so far — everything else on the map is
// a future slice. This is presentation-only (which links are clickable),
// not a role/security decision, so it stays local to the sidebar.
const BUILT_ROUTES = new Set(["/", "/cameras"]);

export function Sidebar() {
  const pathname = usePathname();
  const [routes, setRoutes] = useState<NavRoute[]>([]);

  useEffect(() => {
    getNavRoutes()
      .then(setRoutes)
      .catch(() => {
        // A 401 here is already handled by the API client.
      });
  }, []);

  return (
    <nav className="w-56 shrink-0 border-r border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
      <ul className="space-y-1">
        {routes.map((route) => {
          const isBuilt = BUILT_ROUTES.has(route.path);
          const active = pathname === route.path;

          if (!isBuilt) {
            return (
              <li key={route.path}>
                <span className="flex items-center justify-between rounded-lg px-3 py-2 text-sm text-zinc-400 dark:text-zinc-600">
                  {route.label}
                  <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] font-medium text-zinc-400 dark:bg-zinc-800 dark:text-zinc-500">
                    soon
                  </span>
                </span>
              </li>
            );
          }

          return (
            <li key={route.path}>
              <Link
                href={route.path}
                className={`block rounded-lg px-3 py-2 text-sm font-medium transition ${
                  active
                    ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300"
                    : "text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
                }`}
              >
                {route.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
