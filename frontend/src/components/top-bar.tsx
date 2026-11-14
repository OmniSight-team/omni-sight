"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { type LiveCamera, listLiveCameras } from "@/lib/api-client";

// The top bar in the "Night shift" look (frontend redesign): the mark, a way into Search from
// anywhere (also the / key, see keyboard-shortcuts.tsx), how many cameras are live, the time,
// and the account menu.

// The camera wall's own source of truth (`GET /cameras/live`); refreshed at the dashboard's pace.
const LIVE_POLL_MS = 30_000;

const clockFormat = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function Clock() {
  // Set after mounting, so the server and the first render agree.
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    const tick = () => setNow(new Date());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  if (!now) return null;
  return (
    <time dateTime={now.toISOString()} className="text-[15px] font-medium tracking-wide text-ns-text tabular-nums">
      {clockFormat.format(now)}
    </time>
  );
}

function LivePill() {
  const [cameras, setCameras] = useState<LiveCamera[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      listLiveCameras()
        .then((rows) => {
          if (!cancelled) setCameras(rows);
        })
        .catch(() => {
          // Non-fatal: the pill is left out rather than showing a wrong count.
        });
    void load();
    const id = setInterval(load, LIVE_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);
  if (cameras === null || cameras.length === 0) return null;
  const live = cameras.filter((camera) => camera.state === "live").length;
  return (
    <Link
      href="/live"
      className="flex items-center gap-2 rounded-full border border-ns-line px-3 py-1 text-sm text-ns-soft no-underline transition hover:border-ns-line-strong hover:text-ns-text focus-visible:ring-2 focus-visible:ring-ns-accent focus-visible:outline-none"
    >
      <span
        aria-hidden="true"
        className={`size-2 rounded-full ${live > 0 ? "bg-ns-live motion-safe:animate-ns-breathe" : "bg-ns-attention"}`}
      />
      {live} of {cameras.length} cameras live
    </Link>
  );
}

function AccountMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={box} className="relative">
      {/* A plain disclosure, not an ARIA menu: one item does not need arrow-key navigation. */}
      <button
        type="button"
        aria-expanded={open}
        aria-controls="account-panel"
        aria-label={`Account: ${user?.email ?? ""}`}
        onClick={() => setOpen((value) => !value)}
        className="flex size-9 items-center justify-center rounded-full border border-ns-line-strong bg-ns-raised text-sm font-semibold text-ns-text transition hover:border-ns-accent focus-visible:ring-2 focus-visible:ring-ns-accent focus-visible:outline-none"
      >
        {user?.email.slice(0, 1).toUpperCase()}
      </button>
      {open && (
        <div
          id="account-panel"
          className="absolute right-0 z-20 mt-2 w-60 rounded-lg border border-ns-line-strong bg-ns-raised p-1.5 shadow-[0_12px_32px_rgba(0,0,0,0.45)]"
        >
          <p className="truncate px-2.5 pt-1.5 text-sm text-ns-text">{user?.email}</p>
          <p className="px-2.5 pb-2 text-[13px] text-ns-muted capitalize">{user?.role}</p>
          <button
            type="button"
            onClick={logout}
            className="w-full rounded-md px-2.5 py-2 text-left text-sm text-ns-text transition hover:bg-ns-selected focus-visible:bg-ns-selected focus-visible:outline-none"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function TopBar() {
  return (
    <header className="flex h-14 shrink-0 items-center gap-6 border-b border-ns-line bg-ns-chrome px-5">
      <Link
        href="/"
        className="flex flex-none items-center gap-2.5 rounded text-ns-text no-underline focus-visible:ring-2 focus-visible:ring-ns-accent focus-visible:outline-none"
      >
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true" className="text-ns-accent">
          <circle cx="12" cy="12" r="9.5" />
          <circle cx="12" cy="12" r="3.2" fill="currentColor" stroke="none" />
          <path d="M2.5 12h3M18.5 12h3" strokeLinecap="round" />
        </svg>
        <span className="text-base font-semibold">OmniSight</span>
      </Link>

      <Link
        href="/search"
        className="hidden h-9 max-w-[520px] flex-1 items-center gap-2.5 rounded-md border border-ns-line bg-ns-ground px-3 text-sm text-ns-muted no-underline transition hover:border-ns-line-strong focus-visible:ring-2 focus-visible:ring-ns-accent focus-visible:outline-none sm:flex"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
        </svg>
        <span className="flex-1">Search footage…</span>
        <kbd className="rounded border border-ns-line-strong px-1.5 font-[inherit] text-xs text-ns-soft">/</kbd>
      </Link>

      <div className="ml-auto flex flex-none items-center gap-4">
        <LivePill />
        <Clock />
        <AccountMenu />
      </div>
    </header>
  );
}
