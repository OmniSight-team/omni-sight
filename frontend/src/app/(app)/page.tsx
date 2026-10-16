"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  type DashboardHour,
  type DashboardSummary,
  type Dataset,
  getDashboardActivity,
  getDashboardSummary,
  getNavRoutes,
  listDatasets,
} from "@/lib/api-client";

// The landing page after sign-in (OMNI-611, FR-9): the state of the whole system at a
// glance. Every figure comes from the API (OMNI-610's rollup) and links to the screen
// behind it. Refreshed every 30 s while the tab is visible, and at once when it comes back.

const REFRESH_MS = 30_000;

interface Snapshot {
  summary: DashboardSummary;
  activity: DashboardHour[];
  datasets: Dataset[];
  // Whether this user may open the camera wall (Live Monitoring is operators' and admins').
  canSeeWall: boolean;
  at: Date;
}

async function loadSnapshot(): Promise<Snapshot> {
  const [summary, activity, datasets, routes] = await Promise.all([
    getDashboardSummary(),
    getDashboardActivity(24),
    listDatasets(),
    getNavRoutes(),
  ]);
  return { summary, activity, datasets, canSeeWall: routes.some((r) => r.path === "/live"), at: new Date() };
}

function useDocumentVisible(): boolean {
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const update = () => setVisible(document.visibilityState === "visible");
    update();
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  return visible;
}

const number = new Intl.NumberFormat();

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function formatHour(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}

const CARD =
  "block rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900";
const CARD_LINK = `${CARD} transition hover:border-indigo-300 hover:shadow focus-visible:outline-2 focus-visible:outline-indigo-500 dark:hover:border-indigo-800`;

function Figure({
  href,
  label,
  value,
  detail,
  destination,
}: {
  href: string | null;
  label: string;
  value: string;
  detail: string;
  destination: string;
}) {
  const body = (
    <>
      <p className="text-sm text-zinc-500 dark:text-zinc-400">{label}</p>
      <p className="mt-2 text-3xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">{value}</p>
      <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{detail}</p>
      <p className="mt-4 text-xs font-medium text-indigo-600 dark:text-indigo-400">
        {href ? `${destination} →` : destination}
      </p>
    </>
  );
  if (href === null) {
    return <div className={CARD}>{body}</div>;
  }
  return (
    <Link href={href} className={CARD_LINK} aria-label={`${label}: ${value}. ${destination}`}>
      {body}
    </Link>
  );
}

function ActivityChart({ hours }: { hours: DashboardHour[] }) {
  const max = Math.max(1, ...hours.map((h) => h.segments));
  const total = hours.reduce((sum, h) => sum + h.segments, 0);

  return (
    <div className={CARD}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="font-medium text-zinc-900 dark:text-zinc-50">Activity, last 24 hours</h2>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Segments stored per hour: {number.format(total)} in all
          </p>
        </div>
        <Link
          href="/videos"
          className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
        >
          Video archive →
        </Link>
      </div>

      <div className="mt-4 flex">
        <div className="flex h-40 w-14 shrink-0 flex-col justify-between pr-2 text-right text-xs tabular-nums text-zinc-400 dark:text-zinc-500">
          <span>{number.format(max)}</span>
          <span>0</span>
        </div>
        <div className="relative flex h-40 flex-1 items-end gap-0.5 border-b border-l border-zinc-200 dark:border-zinc-700">
          {total === 0 && (
            <p className="absolute inset-0 flex items-center justify-center text-sm text-zinc-400 dark:text-zinc-500">
              Nothing stored in the last 24 hours
            </p>
          )}
          {hours.map((h, i) => (
            <div
              key={h.hour}
              tabIndex={0}
              aria-label={`${formatHour(h.hour)}: ${number.format(h.segments)} segments`}
              className="group relative flex h-full flex-1 items-end outline-none"
            >
              <div
                className="w-full rounded-t-[4px] bg-indigo-500 group-hover:bg-indigo-600 group-focus:bg-indigo-600 dark:bg-indigo-400 dark:group-hover:bg-indigo-300 dark:group-focus:bg-indigo-300"
                style={{ height: h.segments > 0 ? `max(2px, ${(h.segments / max) * 100}%)` : "0" }}
              />
              <div className={`pointer-events-none absolute bottom-full z-10 mb-1 hidden whitespace-nowrap ${
                  // Kept inside the card at both ends of the axis.
                  i < 3 ? "left-0" : i >= hours.length - 3 ? "right-0" : "left-1/2 -translate-x-1/2"
                } rounded-lg bg-zinc-900 px-2.5 py-1.5 text-xs text-white shadow group-hover:block group-focus:block dark:bg-zinc-100 dark:text-zinc-900`}>
                <span className="font-medium">{formatHour(h.hour)}</span> · {number.format(h.segments)} segments
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="ml-14 mt-1 flex text-xs text-zinc-400 dark:text-zinc-500">
        {hours.map((h, i) => (
          <span key={h.hour} className="flex-1 text-center">
            {i % 6 === 0 || i === hours.length - 1 ? formatHour(h.hour) : ""}
          </span>
        ))}
      </div>

      <table className="sr-only">
        <caption>Segments stored per hour</caption>
        <thead>
          <tr>
            <th>Hour</th>
            <th>Segments</th>
          </tr>
        </thead>
        <tbody>
          {hours.map((h) => (
            <tr key={h.hour}>
              <td>{formatHour(h.hour)}</td>
              <td>{h.segments}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DashboardPage() {
  const visible = useDocumentVisible();
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    loadSnapshot()
      .then((next) => {
        setSnapshot(next);
        setError(null);
      })
      .catch((err) => {
        // A 401 is handled by the API client (back to sign-in).
        setError(err instanceof ApiError ? err.message : "could not reach the API");
      });
  }, []);

  useEffect(() => {
    if (!visible) return;
    refresh();
    const timer = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(timer);
  }, [visible, refresh]);

  if (snapshot === null) {
    return (
      <main className="p-6">
        <h1 className="mb-4 text-lg font-semibold text-zinc-900 dark:text-zinc-50">Operations Dashboard</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          {error ? `The dashboard could not load: ${error}` : "Loading…"}
        </p>
      </main>
    );
  }

  const { summary, activity, datasets, canSeeWall, at } = snapshot;
  const offline = summary.cameras_total - summary.cameras_online;
  const clipsLoaded = datasets.reduce((sum, d) => sum + d.videos_loaded, 0);
  const clipsTotal = datasets.reduce((sum, d) => sum + d.total, 0);

  return (
    <main className="p-6">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Operations Dashboard</h1>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {error ? (
            <span className="text-red-600 dark:text-red-400">Could not refresh ({error}); showing </span>
          ) : (
            "Updated "
          )}
          {at.toLocaleTimeString()} · refreshes every 30 s
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
        <Figure
          href={canSeeWall ? "/live" : null}
          label="Cameras online"
          value={`${summary.cameras_online} / ${summary.cameras_total}`}
          detail={summary.cameras_total === 0 ? "No camera registered" : `${offline} not live`}
          destination={canSeeWall ? "Camera wall" : "Live Monitoring is for operators"}
        />
        <Figure
          href="/videos"
          label="Footage held"
          value={number.format(summary.videos)}
          detail={summary.videos === 1 ? "video" : "videos, recordings and dataset clips"}
          destination="Video archive"
        />
        <Figure
          href="/videos"
          label="Segments indexed"
          value={number.format(summary.segments)}
          detail="frames scored by the motion gate"
          destination="Video archive"
        />
        <Figure
          href="/videos"
          label="Storage in use"
          value={`${summary.storage_gb.toFixed(2)} GB`}
          detail={
            summary.oldest_recording_at
              ? `Kept ${summary.retention_days} days; oldest recording ${formatDate(summary.oldest_recording_at)}`
              : `Kept ${summary.retention_days} days; no recording due to expire`
          }
          destination="Video archive"
        />
        <Figure
          href="/datasets"
          label="Datasets"
          value={`${clipsLoaded} / ${clipsTotal}`}
          detail={`clips loaded across ${datasets.length} datasets`}
          destination="Datasets"
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ActivityChart hours={activity} />
        </div>
        <div className={CARD}>
          <h2 className="font-medium text-zinc-900 dark:text-zinc-50">Alerts needing attention</h2>
          <p className="mt-6 text-sm text-zinc-500 dark:text-zinc-400">Alerts arrive in slice 9.</p>
          <p className="mt-2 text-xs text-zinc-400 dark:text-zinc-500">
            Nothing is counted here until then: no alerts is not the same as zero alerts.
          </p>
        </div>
      </div>
    </main>
  );
}
