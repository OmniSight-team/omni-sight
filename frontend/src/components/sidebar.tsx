"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { getNavRoutes, type NavRoute } from "@/lib/api-client";
import { openShortcuts } from "@/components/keyboard-shortcuts";

// The screens that have a real page so far — everything else on the map is
// a future slice. This is presentation-only (which links are clickable),
// not a role/security decision, so it stays local to the sidebar.
const BUILT_ROUTES = new Set(["/", "/live", "/search", "/cameras", "/videos"]);

// "Night shift" (frontend redesign): the screens an operator watches with, then the ones that set
// the system up. Which routes a role sees still comes from `GET /nav`; only the grouping and the
// plainer names are decided here.
const WATCH = ["/", "/live", "/search", "/videos"];
const SET_UP = ["/cameras"];

const LABELS: Record<string, string> = {
  "/": "Dashboard",
  "/live": "Live monitoring",
  "/videos": "Video archive",
  "/reports": "Incident reports",
};

function label(route: NavRoute): string {
  return LABELS[route.path] ?? route.label;
}

function isActive(path: string, pathname: string): boolean {
  return path === "/" ? pathname === "/" : pathname === path || pathname.startsWith(`${path}/`);
}

function NavLink({ route, pathname }: { route: NavRoute; pathname: string }) {
  const active = isActive(route.path, pathname);
  return (
    <li>
      <Link
        href={route.path}
        aria-current={active ? "page" : undefined}
        className={`flex items-center gap-3 rounded-md px-3 py-2 no-underline transition focus-visible:ring-2 focus-visible:ring-ns-accent focus-visible:outline-none ${
          active ? "bg-ns-raised font-medium text-ns-text" : "text-ns-soft hover:bg-ns-raised/60 hover:text-ns-text"
        }`}
      >
        <span aria-hidden="true" className={`-ml-2 h-[18px] w-[3px] rounded-sm ${active ? "bg-ns-accent" : "bg-transparent"}`} />
        {label(route)}
      </Link>
    </li>
  );
}

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

  const built = (paths: string[]) =>
    paths.map((path) => routes.find((route) => route.path === path)).filter((route) => route !== undefined);
  const watch = built(WATCH);
  const setUp = built(SET_UP);
  const later = routes.filter((route) => !BUILT_ROUTES.has(route.path));

  return (
    <nav
      aria-label="Main"
      className="flex w-60 shrink-0 flex-col border-r border-ns-line bg-ns-chrome px-3 py-5 text-[15px]"
    >
      {watch.length > 0 && (
        <>
          <p className="mx-3 mb-1.5 text-xs text-ns-muted">Watch</p>
          <ul className="space-y-0.5">
            {watch.map((route) => (
              <NavLink key={route.path} route={route} pathname={pathname} />
            ))}
          </ul>
        </>
      )}
      {setUp.length > 0 && (
        <>
          <p className="mx-3 mt-6 mb-1.5 text-xs text-ns-muted">Set up</p>
          <ul className="space-y-0.5">
            {setUp.map((route) => (
              <NavLink key={route.path} route={route} pathname={pathname} />
            ))}
          </ul>
        </>
      )}
      <div className="mt-auto space-y-3.5 px-3 pt-8 text-[13px] leading-normal text-ns-muted">
        {later.length > 0 && (
          <p>Coming later: {later.map((route) => label(route).toLowerCase()).join(", ")}.</p>
        )}
        <button
          type="button"
          onClick={openShortcuts}
          className="flex items-center gap-2 rounded text-ns-muted transition hover:text-ns-text focus-visible:ring-2 focus-visible:ring-ns-accent focus-visible:outline-none"
        >
          <kbd className="rounded border border-ns-line-strong px-1.5 font-[inherit] text-xs text-ns-soft">?</kbd>
          Keyboard shortcuts
        </button>
      </div>
    </nav>
  );
}
