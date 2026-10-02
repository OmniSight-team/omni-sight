"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, fetchCameraPreview, type LiveCamera, type LiveState, listLiveCameras } from "@/lib/api-client";

// The wall (OMNI-506): a fixed 3x3 grid. More cameras than this go on pages,
// never into smaller tiles.
const TILES_PER_PAGE = 9;
// How often each tile asks for its camera's current frame. The preview is
// rewritten at most every 0.5 s (OMNI-503), so once a second is about every
// second frame, at one small JPEG or a 304 per tile.
const PREVIEW_POLL_MS = 1000;
// How often the cameras, their groups and their states are refreshed. The API
// calls a camera frozen 3 s after its last frame (OMNI-504), so a tile says so
// within about five seconds.
const CAMERAS_POLL_MS = 2000;
const ALL_GROUPS = "";

// Whether anyone is looking. Every poll on this screen checks it: a wall left
// open in a background tab must not keep sixteen requests a second going.
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

// A frame that has not been replaced for longer than this does not get the
// live dot's tick, whatever the last state said: the tick is local evidence that
// pictures are still arriving, between two refreshes of the state.
const TICK_STALE_MS = 3000;

function formatAge(seconds: number): string {
  if (seconds < 2) return "just now";
  if (seconds < 90) return `${Math.floor(seconds)} s ago`;
  if (seconds < 5400) return `${Math.floor(seconds / 60)} min ago`;
  return `${Math.floor(seconds / 3600)} h ago`;
}

// A clock for "last frame 12 s ago", ticking once a second while visible.
function useNow(visible: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!visible) return;
    const tick = () => setNow(Date.now());
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [visible]);
  return now;
}

type Icon = (props: { className?: string }) => React.ReactElement;

const PauseIcon: Icon = ({ className }) => (
  <svg viewBox="0 0 16 16" aria-hidden="true" className={className}>
    <rect x="3.5" y="3" width="3" height="10" rx="1" fill="currentColor" />
    <rect x="9.5" y="3" width="3" height="10" rx="1" fill="currentColor" />
  </svg>
);

const UnpluggedIcon: Icon = ({ className }) => (
  <svg viewBox="0 0 16 16" aria-hidden="true" className={className}>
    <path d="M2 14 14 2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    <path d="M5.5 4.5 4 6a3 3 0 0 0 0 4.2l1.8 1.8a3 3 0 0 0 4.2 0l1.5-1.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    <path d="M9 3.5 10.5 2M12.5 7 14 5.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
  </svg>
);

const StopIcon: Icon = ({ className }) => (
  <svg viewBox="0 0 16 16" aria-hidden="true" className={className}>
    <rect x="3.5" y="3.5" width="9" height="9" rx="1.5" fill="currentColor" />
  </svg>
);

// What a tile says when it is not live (OMNI-507). Each state its own label,
// icon and colour, so frozen, offline and stopped are never mistaken for one
// another, or for a picture that is still coming in.
const NOT_LIVE: Record<Exclude<LiveState, "live">, { label: string; detail: string; Icon: Icon; badge: string }> = {
  frozen: {
    label: "Frozen",
    detail: "The stream is open but no new picture is arriving.",
    Icon: PauseIcon,
    badge: "bg-amber-500 text-black",
  },
  offline: {
    label: "Offline",
    detail: "The camera cannot be reached; reconnecting.",
    Icon: UnpluggedIcon,
    badge: "bg-red-600 text-white",
  },
  stopped: {
    label: "Stopped",
    detail: "This camera is not being captured.",
    Icon: StopIcon,
    badge: "bg-zinc-600 text-white",
  },
};

// One camera's tile. It asks for the current frame about once a second with the
// ETag of the frame it is showing (fetch -> blob -> object URL), so an
// unchanged frame costs a 304 and no image. The previous object URL is revoked
// when a new one replaces it, so a wall left open for hours does not hold every
// frame it ever showed. No video element, no stream.
//
// What the tile says comes from the camera's state (`GET /cameras/live`,
// OMNI-504). The live dot is quiet: it ticks only when a new frame has actually
// arrived (the preview's ETag changed), so a picture that stopped changing
// cannot look live. Every other state is labelled, with the last frame dimmed
// and its age, or a panel saying why there is no picture: never a black box.
function CameraTile({ camera, visible, now }: { camera: LiveCamera; visible: boolean; now: number }) {
  const [src, setSrc] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  // How many new frames have arrived, and when the newest did (local clock).
  const [frames, setFrames] = useState(0);
  const [newFrameAt, setNewFrameAt] = useState<number | null>(null);
  const [frameWrittenAt, setFrameWrittenAt] = useState<number | null>(null);
  // Kept across a hidden tab, so the first poll back can still be a 304.
  const etag = useRef<string | null>(null);
  const shown = useRef<string | null>(null);
  const polling = visible && camera.state !== "stopped";

  useEffect(() => {
    // A stopped camera has no preview to ask for (its worker removed it); the
    // last frame already on screen stays, dimmed, until it starts again.
    if (!polling) return;
    let cancelled = false;
    let inFlight = false;

    async function poll() {
      // A slow response must not pile a second request up behind it.
      if (inFlight) return;
      inFlight = true;
      try {
        const result = await fetchCameraPreview(camera.camera_id, etag.current);
        if (cancelled) return;
        if (result.kind === "frame") {
          const url = URL.createObjectURL(result.blob);
          if (shown.current) URL.revokeObjectURL(shown.current);
          shown.current = url;
          etag.current = result.etag;
          setSrc(url);
          setFrames((count) => count + 1);
          setNewFrameAt(Date.now());
          setFrameWrittenAt(result.lastModified ? Date.parse(result.lastModified) : null);
          setProblem(null);
        } else if (result.kind === "none") {
          // Keep the last picture, if there is one; the state says why it is old.
          etag.current = null;
          setProblem(result.reason);
        } else {
          setProblem(null);
        }
      } catch (err) {
        if (!cancelled && !(err instanceof ApiError && err.status === 401)) {
          setProblem("Could not load the picture — retrying.");
        }
      } finally {
        inFlight = false;
      }
    }

    poll();
    const timer = setInterval(poll, PREVIEW_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [camera.camera_id, polling]);

  // The frame on screen stays while the tab is hidden; its object URL is
  // released when a newer one replaces it (above) or the tile goes away.
  useEffect(() => {
    return () => {
      if (shown.current) URL.revokeObjectURL(shown.current);
      shown.current = null;
    };
  }, []);

  // When the newest frame was written: the state's `last_frame_at`, or the
  // preview's own `Last-Modified`, whichever is newer.
  const fromState = camera.last_frame_at ? Date.parse(camera.last_frame_at) : null;
  const writtenAt = Math.max(fromState ?? 0, frameWrittenAt ?? 0) || null;
  const age = writtenAt !== null ? Math.max(0, (now - writtenAt) / 1000) : null;
  const live = camera.state === "live";
  const ticking = live && newFrameAt !== null && now - newFrameAt <= TICK_STALE_MS;
  const notLive = camera.state === "live" ? null : NOT_LIVE[camera.state];

  return (
    <figure className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      {/* The picture takes whatever height the row leaves it and is letterboxed
          into it, so the whole 3x3 wall fits the window at any size. */}
      <div className={`relative min-h-0 flex-1 ${src ? "bg-black" : "bg-zinc-800"}`}>
        {src ? (
          // An object URL from an authenticated fetch, not something Next's image optimizer can load.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={src}
            alt={`${live ? "Current" : "Last"} frame from ${camera.name}`}
            className={`h-full w-full object-contain transition ${live ? "" : "opacity-40 grayscale"}`}
          />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-2 px-4 text-center text-xs text-zinc-300">
            {notLive ? <notLive.Icon className="h-6 w-6 opacity-70" /> : null}
            <span>{notLive ? notLive.detail : (problem ?? "Waiting for the first picture…")}</span>
          </div>
        )}

        {live && (
          <span
            className="absolute left-2 top-2 flex items-center gap-1.5 rounded-md bg-black/55 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-zinc-100"
            title={ticking ? "New pictures are arriving" : "No new picture for a few seconds"}
          >
            {/* Re-mounted on every new frame, so its short flash marks a frame
                actually arriving and nothing else. */}
            <span
              key={frames}
              className={`h-2 w-2 rounded-full ${ticking ? "animate-[ping_0.6s_ease-out_1] bg-emerald-400" : "bg-zinc-400"}`}
            />
            Live
          </span>
        )}

        {notLive && (
          <span
            className={`absolute left-2 top-2 flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${notLive.badge}`}
          >
            <notLive.Icon className="h-3 w-3" />
            {notLive.label}
          </span>
        )}

        {notLive && src && (
          <span className="absolute bottom-2 left-2 right-2 truncate rounded-md bg-black/70 px-2 py-1 text-[11px] text-zinc-100">
            {age !== null ? `Last frame ${formatAge(age)}` : "Last frame"} · {notLive.detail}
          </span>
        )}
      </div>
      <figcaption className="px-3 py-2">
        <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-50">{camera.name}</p>
        <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">{camera.location}</p>
      </figcaption>
    </figure>
  );
}

export default function LiveMonitoringPage() {
  const visible = useDocumentVisible();
  const now = useNow(visible);
  const [cameras, setCameras] = useState<LiveCamera[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [group, setGroup] = useState<string>(ALL_GROUPS);
  const [page, setPage] = useState(0);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    async function load() {
      try {
        const next = await listLiveCameras();
        if (cancelled) return;
        setCameras(next);
        setLoadError(null);
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : "Could not load the cameras — retrying.");
      }
    }
    load();
    const timer = setInterval(load, CAMERAS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [visible]);

  const groups = useMemo(
    () => Array.from(new Set((cameras ?? []).map((camera) => camera.group_name))).sort(),
    [cameras],
  );
  const shown = useMemo(
    () => (cameras ?? []).filter((camera) => group === ALL_GROUPS || camera.group_name === group),
    [cameras, group],
  );
  const pages = Math.max(1, Math.ceil(shown.length / TILES_PER_PAGE));
  const current = Math.min(page, pages - 1);
  const onPage = shown.slice(current * TILES_PER_PAGE, (current + 1) * TILES_PER_PAGE);

  return (
    <main className="p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Live Monitoring</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {cameras === null
              ? "Loading cameras…"
              : `${shown.length} camera${shown.length === 1 ? "" : "s"}${group ? ` in ${group}` : ""}`}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
            Group
            <select
              value={group}
              onChange={(event) => {
                setGroup(event.target.value);
                setPage(0);
              }}
              className="rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            >
              <option value={ALL_GROUPS}>All groups</option>
              {groups.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>

          {pages > 1 && (
            <div className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
              <button
                type="button"
                onClick={() => setPage(Math.max(0, current - 1))}
                disabled={current === 0}
                className="rounded-lg border border-zinc-300 px-3 py-1.5 transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-700 dark:hover:bg-zinc-800"
              >
                Previous
              </button>
              <span className="tabular-nums">
                Page {current + 1} of {pages}
              </span>
              <button
                type="button"
                onClick={() => setPage(Math.min(pages - 1, current + 1))}
                disabled={current >= pages - 1}
                className="rounded-lg border border-zinc-300 px-3 py-1.5 transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-700 dark:hover:bg-zinc-800"
              >
                Next
              </button>
            </div>
          )}
        </div>
      </div>

      {loadError && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
          {loadError}
        </p>
      )}

      {cameras !== null && shown.length === 0 ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">No cameras{group ? " in this group" : ""} yet.</p>
      ) : (
        // Three rows sized to the window, not to the tiles' width: on a wide screen
        // width-sized tiles push the third row off the bottom, and the wall must
        // show all nine at once. 11rem is the top bar, this page's padding and
        // its heading; the minimum keeps tiles usable in a short window.
        <div className="grid h-[calc(100vh-11rem)] min-h-[30rem] grid-cols-3 grid-rows-3 gap-3">
          {onPage.map((camera) => (
            <CameraTile key={camera.camera_id} camera={camera} visible={visible} now={now} />
          ))}
        </div>
      )}
    </main>
  );
}
