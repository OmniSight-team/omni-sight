"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  type Camera,
  type CameraFrame,
  type CameraStats,
  getCameraStats,
  listCameraFrames,
  listCameras,
  startCamera,
  stopCamera,
} from "@/lib/api-client";

// How often the screen asks what changed. Two seconds is quick enough that a
// dropped stream shows within a moment, and slow enough that one open screen
// costs three small requests every two seconds, not a stream.
const POLL_MS = 2000;
// The rolling strip keeps this many of the newest frames.
const STRIP_SIZE = 24;
// A running camera whose newest frame is older than this is not delivering.
const STALE_FRAME_S = 10;

type Busy = "starting" | "stopping" | null;
type View = "running" | "stopped" | "unreachable" | "disabled" | "starting" | "stopping";

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

// Whether the camera is being captured, and what state it is in, are two
// separate facts held in two places: `status` says whether its stream is
// reachable, the stats say whether a worker is running (uptime is 0 otherwise).
// The screen shows them as one state a person can read at a glance.
function viewOf(camera: Camera, stats: CameraStats | null, busy: Busy): View {
  if (busy) return busy;
  if (camera.status === "disabled") return "disabled";
  if (camera.status === "unreachable") return "unreachable";
  if (stats !== null && stats.uptime_s > 0) return "running";
  return "stopped";
}

const VIEW_STYLES: Record<View, { label: string; pill: string; dot: string }> = {
  running: {
    label: "Running",
    pill: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
    dot: "bg-emerald-500",
  },
  stopped: {
    label: "Stopped",
    pill: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
    dot: "bg-zinc-400",
  },
  unreachable: {
    label: "Unreachable",
    pill: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400",
    dot: "bg-red-500",
  },
  disabled: {
    label: "Disabled",
    pill: "bg-zinc-100 text-zinc-400 line-through dark:bg-zinc-800 dark:text-zinc-600",
    dot: "bg-zinc-300 dark:bg-zinc-600",
  },
  starting: {
    label: "Starting…",
    pill: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
    dot: "bg-amber-500",
  },
  stopping: {
    label: "Stopping…",
    pill: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
    dot: "bg-amber-500",
  },
};

function StatusPill({ view, reconnecting }: { view: View; reconnecting: boolean }) {
  const style = VIEW_STYLES[view];
  const alive = view === "running";
  const pulsing = view === "starting" || view === "stopping" || (view === "unreachable" && reconnecting);
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-medium ${style.pill}`}
    >
      <span className="relative flex h-2.5 w-2.5">
        {(alive || pulsing) && (
          <span
            className={`absolute inline-flex h-full w-full rounded-full opacity-60 ${style.dot} ${
              alive ? "animate-ping" : "animate-pulse"
            }`}
          />
        )}
        <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${style.dot}`} />
      </span>
      {style.label}
      {view === "unreachable" && reconnecting && (
        <span className="text-xs font-normal opacity-80">— reconnecting</span>
      )}
    </span>
  );
}

function formatUptime(seconds: number): string {
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(secs).padStart(2, "0")}s`;
  if (minutes > 0) return `${minutes}m ${String(secs).padStart(2, "0")}s`;
  return `${secs}s`;
}

function formatAge(seconds: number): string {
  if (seconds < 2) return "just now";
  if (seconds < 90) return `${Math.floor(seconds)} s ago`;
  if (seconds < 5400) return `${Math.floor(seconds / 60)} min ago`;
  return `${Math.floor(seconds / 3600)} h ago`;
}

function formatClock(timestampS: number): string {
  return new Date(timestampS * 1000).toLocaleTimeString();
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-zinc-400 dark:text-zinc-500">{hint}</p>}
    </div>
  );
}

// "Is it keeping up?" — answered by the drop count, the honest one, and by
// whether it is still going up right now, which is what tells a camera that
// fell behind and recovered from one that is falling behind at this moment.
function DropIndicator({
  stats,
  droppingNow,
  capturing,
}: {
  stats: CameraStats;
  droppingNow: boolean;
  capturing: boolean;
}) {
  const percent = stats.captured > 0 ? (stats.dropped / stats.captured) * 100 : 0;
  const share = `${stats.dropped.toLocaleString()} of ${stats.captured.toLocaleString()} sampled frames (${percent.toFixed(1)}%)`;

  let tone = "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300";
  let headline = "Keeping up";
  let detail = stats.captured > 0 ? "No frames have been dropped." : "Nothing captured yet.";
  if (droppingNow && capturing) {
    tone = "animate-pulse border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300";
    headline = "Falling behind — dropping frames now";
    detail = `${share} dropped so far.`;
  } else if (stats.dropped > 0) {
    tone = "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300";
    headline = capturing ? "Keeping up now — frames were dropped earlier" : "Frames were dropped";
    detail = `${share} dropped in total.`;
  }

  return (
    <div className={`rounded-xl border p-4 ${tone}`} role="status" aria-live="polite">
      <p className="text-sm font-semibold">{headline}</p>
      <p className="mt-0.5 text-sm">{detail}</p>
    </div>
  );
}

export default function CameraDetailPage() {
  const params = useParams<{ id: string }>();
  const cameraId = Number(params.id);

  const [camera, setCamera] = useState<Camera | null>(null);
  const [stats, setStats] = useState<CameraStats | null>(null);
  const [frames, setFrames] = useState<CameraFrame[]>([]);
  const [droppingNow, setDroppingNow] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [now, setNow] = useState(0);
  const pollNow = useRef<(() => void) | null>(null);

  // Ticks once a second so "3 s ago" keeps counting between polls.
  useEffect(() => {
    const tick = () => setNow(Date.now() / 1000);
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    let newestSeen: number | null = null;
    let lastDropped: number | null = null;

    async function poll() {
      // A slow response must not pile up a second request behind it.
      if (inFlight) return;
      inFlight = true;
      try {
        const [cameras, nextStats, fresh] = await Promise.all([
          listCameras(),
          getCameraStats(cameraId),
          listCameraFrames(cameraId, newestSeen === null ? { limit: STRIP_SIZE } : { since: newestSeen }),
        ]);
        if (cancelled) return;

        const found = cameras.find((entry) => entry.id === cameraId) ?? null;
        setCamera(found);
        setStats(nextStats);
        if (lastDropped !== null) setDroppingNow(nextStats.dropped > lastDropped);
        lastDropped = nextStats.dropped;

        if (fresh.length > 0) {
          newestSeen = fresh[fresh.length - 1].timestamp_s;
          // Oldest first from the API; the strip shows the newest on the left.
          setFrames((previous) => [...fresh.slice().reverse(), ...previous].slice(0, STRIP_SIZE));
        }
        setLoadError(found ? null : "This camera does not exist.");
      } catch (err) {
        if (!cancelled) setLoadError(errorMessage(err, "Could not refresh — retrying."));
      } finally {
        inFlight = false;
      }
    }

    pollNow.current = poll;
    poll();
    const timer = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
      pollNow.current = null;
    };
  }, [cameraId]);

  async function handleStart() {
    setBusy("starting");
    setActionError(null);
    try {
      await startCamera(cameraId);
    } catch (err) {
      setActionError(errorMessage(err, "Could not start capture."));
    } finally {
      setBusy(null);
      pollNow.current?.();
    }
  }

  async function handleStop() {
    setBusy("stopping");
    setActionError(null);
    try {
      await stopCamera(cameraId);
    } catch (err) {
      setActionError(errorMessage(err, "Could not stop capture."));
    } finally {
      setBusy(null);
      pollNow.current?.();
    }
  }

  const view: View | null = camera ? viewOf(camera, stats, busy) : null;
  const capturing = stats !== null && stats.uptime_s > 0;
  const newest = frames[0] ?? null;
  const newestAge = newest && now > 0 ? Math.max(0, now - newest.timestamp_s) : null;
  const delivering = view === "running" && newestAge !== null && newestAge <= STALE_FRAME_S;

  const canStart = view === "stopped" || (view === "unreachable" && !capturing);
  const canStop = view === "running" || (view === "unreachable" && capturing);

  return (
    <main className="p-6">
      <Link
        href="/cameras"
        className="mb-4 inline-block text-sm text-zinc-500 hover:underline dark:text-zinc-400"
      >
        ← Cameras
      </Link>

      {loadError && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
          {loadError}
        </p>
      )}

      {camera === null || view === null ? (
        !loadError && <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading camera…</p>
      ) : (
        <div className="min-w-0 space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="truncate text-lg font-semibold text-zinc-900 dark:text-zinc-50">{camera.name}</h1>
                <StatusPill view={view} reconnecting={capturing} />
              </div>
              <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
                {camera.location} · {camera.group}
                {view === "unreachable" && camera.last_seen_at && (
                  <> · last seen {new Date(camera.last_seen_at).toLocaleTimeString()}</>
                )}
              </p>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleStart}
                disabled={!canStart}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {busy === "starting" ? "Starting…" : "Start"}
              </button>
              <button
                type="button"
                onClick={handleStop}
                disabled={!canStop}
                className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
              >
                {busy === "stopping" ? "Stopping…" : "Stop"}
              </button>
            </div>
          </div>

          {busy === "starting" && (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              Waiting for the stream&apos;s first frame — this can take several seconds.
            </p>
          )}
          {view === "disabled" && (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              This camera is disabled. Enable it from the Cameras list to capture from it.
            </p>
          )}
          {actionError && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
              {actionError}
            </p>
          )}

          {/* minmax(0, ...) so a wide child (the frames strip) can never stretch a
              column: a grid track defaults to at least its content's width. */}
          <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <div className="min-w-0">
              <div className="relative aspect-video w-full overflow-hidden rounded-2xl border border-zinc-200 bg-black dark:border-zinc-800">
                {newest ? (
                  // Thumbnails are served directly by nginx (OMNI-307), not through Next's image optimizer.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={newest.thumb_url}
                    alt={`Latest frame from ${camera.name}`}
                    className={`h-full w-full object-contain transition ${delivering ? "" : "opacity-50 grayscale"}`}
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center px-6 text-center text-sm text-zinc-400">
                    {view === "running" || view === "starting"
                      ? "Waiting for the first frame…"
                      : "No frames yet. Start the camera to see what it captures."}
                  </div>
                )}
                {newest && (
                  <span
                    className={`absolute left-3 top-3 rounded-md px-2 py-1 text-xs font-semibold ${
                      delivering ? "bg-red-600 text-white" : "bg-black/70 text-zinc-200"
                    }`}
                  >
                    {delivering ? "● LIVE" : newestAge !== null ? `Last frame ${formatAge(newestAge)}` : "Last frame"}
                  </span>
                )}
                {newest && (
                  <span className="absolute bottom-3 right-3 rounded-md bg-black/70 px-2 py-1 text-xs tabular-nums text-zinc-200">
                    {formatClock(newest.timestamp_s)}
                  </span>
                )}
              </div>
              <p className="mt-2 text-xs text-zinc-400 dark:text-zinc-500">
                The preview is the newest stored frame, refreshed as frames arrive, not a video stream.
              </p>
            </div>

            <div className="min-w-0 space-y-3">
              {stats && (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <Tile label="Captured" value={stats.captured.toLocaleString()} hint="frames sampled" />
                    <Tile label="Dropped" value={stats.dropped.toLocaleString()} hint="pipeline behind" />
                    <Tile
                      label="Effective rate"
                      value={`${stats.fps_effective.toFixed(1)} fps`}
                      hint="frames processed"
                    />
                    <Tile label="Uptime" value={capturing ? formatUptime(stats.uptime_s) : "—"} hint="this capture" />
                  </div>
                  <DropIndicator stats={stats} droppingNow={droppingNow} capturing={capturing} />
                </>
              )}
            </div>
          </div>

          <div className="min-w-0">
            <h2 className="mb-2 text-sm font-semibold text-zinc-900 dark:text-zinc-50">Newest frames</h2>
            {frames.length === 0 ? (
              <p className="text-sm text-zinc-500 dark:text-zinc-400">
                Frames appear here as they are captured. Only frames the motion gate admits are shown.
              </p>
            ) : (
              <div className="flex gap-2 overflow-x-auto pb-2">
                {frames.map((frame) => (
                  <figure key={frame.segment_id} className="w-32 shrink-0">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={frame.thumb_url}
                      alt={`Frame at ${formatClock(frame.timestamp_s)}`}
                      className="aspect-video w-full rounded-lg border border-zinc-200 bg-zinc-100 object-cover dark:border-zinc-800 dark:bg-zinc-800"
                    />
                    <figcaption className="mt-1 text-[11px] tabular-nums text-zinc-500 dark:text-zinc-400">
                      {formatClock(frame.timestamp_s)}
                    </figcaption>
                  </figure>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </main>
  );
}
