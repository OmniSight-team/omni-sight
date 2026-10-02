"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, fetchCameraPreview, type LiveCamera, listLiveCameras } from "@/lib/api-client";

// The wall (OMNI-506): a fixed 3x3 grid. More cameras than this go on pages,
// never into smaller tiles.
const TILES_PER_PAGE = 9;
// How often each tile asks for its camera's current frame. The preview is
// rewritten at most every 0.5 s (OMNI-503), so once a second is about every
// second frame, at one small JPEG or a 304 per tile.
const PREVIEW_POLL_MS = 1000;
// How often the list of cameras (and their groups) is refreshed.
const CAMERAS_POLL_MS = 5000;
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

// One camera's tile. It asks for the current frame about once a second with the
// ETag of the frame it is showing (fetch -> blob -> object URL), so an
// unchanged frame costs a 304 and no image. The previous object URL is revoked
// when a new one replaces it, so a wall left open for hours does not hold every
// frame it ever showed. No video element, no stream.
function CameraTile({ camera, visible }: { camera: LiveCamera; visible: boolean }) {
  const [src, setSrc] = useState<string | null>(null);
  const [none, setNone] = useState<string | null>(null);
  // Kept across a hidden tab, so the first poll back can still be a 304.
  const etag = useRef<string | null>(null);
  const shown = useRef<string | null>(null);

  useEffect(() => {
    if (!visible) return;
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
          setNone(null);
        } else if (result.kind === "none") {
          etag.current = null;
          setNone(result.reason);
        }
      } catch (err) {
        if (!cancelled && !(err instanceof ApiError && err.status === 401)) {
          setNone("Could not load the picture — retrying.");
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
  }, [camera.camera_id, visible]);

  // The frame on screen stays while the tab is hidden; its object URL is
  // released when a newer one replaces it (above) or the tile goes away.
  useEffect(() => {
    return () => {
      if (shown.current) URL.revokeObjectURL(shown.current);
      shown.current = null;
    };
  }, []);

  const showImage = src !== null && none === null;

  return (
    <figure className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      {/* The picture takes whatever height the row leaves it and is letterboxed
          into it, so the whole 3x3 wall fits the window at any size. */}
      <div className="relative min-h-0 flex-1 bg-black">
        {showImage ? (
          // An object URL from an authenticated fetch, not something Next's image optimizer can load.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt={`Current frame from ${camera.name}`} className="h-full w-full object-contain" />
        ) : (
          <div className="flex h-full w-full items-center justify-center px-4 text-center text-xs text-zinc-400">
            {none ?? "Loading…"}
          </div>
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
            <CameraTile key={camera.camera_id} camera={camera} visible={visible} />
          ))}
        </div>
      )}
    </main>
  );
}
