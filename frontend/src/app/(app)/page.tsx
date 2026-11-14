"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  type Camera,
  type DashboardHour,
  type DashboardSummary,
  type Dataset,
  type EmbeddingStatus,
  type LiveCamera,
  fetchCameraPreview,
  getDashboardActivity,
  getDashboardSummary,
  getEmbeddingStatus,
  getNavRoutes,
  listCameras,
  listDatasets,
  listLiveCameras,
} from "@/lib/api-client";

// The landing page after sign-in (OMNI-611, FR-9), in the "Night shift" look (frontend redesign):
// the last 24 hours as one ribbon, one status strip, then the cameras with their pictures and what
// needs a look. Every figure comes from the API and links to the screen behind it. Refreshed every
// 30 s while the tab is visible, and at once when it comes back.

const REFRESH_MS = 30_000;
// A live camera's picture on the dashboard: fresh enough to recognise the scene, not a video.
const PREVIEW_MS = 5_000;
// The dashboard shows this many cameras; the rest are one click away on the wall.
const MAX_TILES = 6;

interface Snapshot {
  summary: DashboardSummary;
  activity: DashboardHour[];
  datasets: Dataset[] | null;
  cameras: Camera[];
  live: LiveCamera[];
  coverage: EmbeddingStatus[] | null;
  routes: Set<string>;
  at: Date;
}

async function loadSnapshot(): Promise<Snapshot> {
  const [summary, activity, routes, cameras, live] = await Promise.all([
    getDashboardSummary(),
    getDashboardActivity(24),
    getNavRoutes(),
    listCameras(),
    listLiveCameras(),
  ]);
  const paths = new Set(routes.map((r) => r.path));
  // Not every role reaches these; the dashboard is still whole without them.
  const [datasets, coverage] = await Promise.all([
    paths.has("/datasets") ? listDatasets().catch(() => null) : Promise.resolve(null),
    getEmbeddingStatus({}).catch(() => null),
  ]);
  return { summary, activity, datasets, cameras, live, coverage, routes: paths, at: new Date() };
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
const dayFormat = new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long" });
const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const secondsFormat = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});
const shortDate = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });

function formatSeen(iso: string | null): string {
  if (!iso) return "never";
  const at = new Date(iso);
  return `${shortDate.format(at)}, ${timeFormat.format(at)}`;
}

const PANEL = "rounded-lg border border-ns-line bg-ns-panel";
const LINK =
  "rounded text-sm text-ns-accent no-underline hover:text-ns-accent-hover hover:underline focus-visible:ring-2 focus-visible:ring-ns-accent focus-visible:outline-none";

// ---- The last 24 hours ----------------------------------------------------------------------

function Ribbon({ hours, animate }: { hours: DashboardHour[]; animate: boolean }) {
  const max = Math.max(1, ...hours.map((h) => h.segments));
  const total = hours.reduce((sum, h) => sum + h.segments, 0);
  const label = (h: DashboardHour) => {
    const start = new Date(h.hour);
    const end = new Date(start.getTime() + 3_600_000);
    return `${timeFormat.format(start)} to ${timeFormat.format(end)}`;
  };

  return (
    <section aria-labelledby="ribbon-title" className={`${PANEL} px-5 pt-4 pb-3`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="ribbon-title" className="text-lg font-semibold">
          Last 24 hours
        </h2>
        <p className="text-[13px] text-ns-muted">
          Frames checked by the motion gate per hour, all footage: {number.format(total)} in all
        </p>
      </div>

      <div className="relative mt-4">
        {total === 0 && (
          <p className="absolute inset-x-0 top-8 text-center text-sm text-ns-muted">
            Nothing came in during the last 24 hours. Start a camera or upload a video.
          </p>
        )}
        <div className="grid h-28 grid-cols-24 items-end gap-1.5 border-b border-ns-line-strong">
          {hours.map((h, i) => (
            <div
              key={h.hour}
              tabIndex={0}
              aria-label={`${label(h)}: ${number.format(h.segments)} frames checked`}
              className="group relative flex h-full items-end rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ns-accent"
            >
              <div
                className={`w-full origin-bottom rounded-t-sm transition-colors ${
                  h.segments > 0 ? "bg-ns-accent group-hover:bg-ns-accent-hover" : "bg-ns-line"
                } ${animate ? "motion-safe:animate-ns-draw" : ""}`}
                style={{
                  height: h.segments > 0 ? `max(3px, ${(h.segments / max) * 100}%)` : "6px",
                  animationDelay: animate ? `${i * 25}ms` : undefined,
                }}
              />
              {/* The bar's own label already says this to a screen reader. */}
              <div
                aria-hidden="true"
                className={`pointer-events-none absolute bottom-full z-10 mb-2 hidden rounded-md border border-ns-line-strong bg-ns-raised px-3 py-2 text-[13px] whitespace-nowrap shadow-[0_8px_24px_rgba(0,0,0,0.35)] group-hover:block group-focus-visible:block ${
                  // Kept inside the panel at both ends of the axis.
                  i < 3 ? "left-0" : i >= hours.length - 3 ? "right-0" : "left-1/2 -translate-x-1/2"
                }`}
              >
                <p className="text-ns-muted">{label(h)}</p>
                <p className="font-semibold text-ns-text">{number.format(h.segments)} frames checked</p>
              </div>
            </div>
          ))}
        </div>
        <span aria-hidden="true" className="absolute -top-2 -right-1.5 -bottom-1 w-0.5 bg-ns-text/50" />
      </div>
      <div className="mt-1.5 grid grid-cols-24 text-xs text-ns-muted" aria-hidden="true">
        {hours.map((h, i) => (
          <span key={h.hour} className={i === hours.length - 1 ? "text-right text-ns-text" : ""}>
            {i === hours.length - 1 ? "Now" : i % 6 === 0 ? timeFormat.format(new Date(h.hour)) : ""}
          </span>
        ))}
      </div>

      <table className="sr-only">
        <caption>Frames checked per hour, last 24 hours</caption>
        <thead>
          <tr>
            <th>Hour</th>
            <th>Frames checked</th>
          </tr>
        </thead>
        <tbody>
          {hours.map((h) => (
            <tr key={h.hour}>
              <td>{label(h)}</td>
              <td>{h.segments}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// ---- The status strip -----------------------------------------------------------------------

function Reading({
  href,
  label,
  value,
  unit,
  note,
  noteTone = "muted",
}: {
  href: string | null;
  label: string;
  value: string;
  unit: string;
  note: string;
  noteTone?: "muted" | "attention";
}) {
  const body = (
    <>
      <p className="text-[13px] text-ns-muted">{label}</p>
      <p className="mt-0.5 text-[26px] leading-tight font-semibold">
        {value}&nbsp;<span className="text-[15px] font-normal text-ns-muted">{unit}</span>
      </p>
      <p className={`mt-0.5 text-[13px] ${noteTone === "attention" ? "text-ns-attention" : "text-ns-muted"}`}>{note}</p>
    </>
  );
  const box = "min-w-[180px] flex-1 border-ns-line px-5 py-3.5 [&:not(:last-child)]:border-r";
  if (href === null) return <div className={box}>{body}</div>;
  return (
    <Link
      href={href}
      className={`${box} text-ns-text no-underline transition hover:bg-ns-raised/50 focus-visible:ring-2 focus-visible:ring-ns-accent focus-visible:outline-none focus-visible:ring-inset`}
    >
      {body}
    </Link>
  );
}

// ---- Cameras ---------------------------------------------------------------------------------

type CameraView = { camera: Camera; live: LiveCamera | undefined };

// What a camera that is not live says, and the step that helps.
function notLive(view: CameraView): { state: string; tone: string; why: string } {
  if (view.camera.status === "disabled") {
    return { state: "Disabled", tone: "bg-ns-muted", why: `Last picture ${formatSeen(view.camera.last_seen_at)}.` };
  }
  switch (view.live?.state) {
    case "frozen":
      return { state: "Frozen", tone: "bg-ns-attention", why: "The stream is open but no new picture is arriving." };
    case "offline":
      return { state: "Offline", tone: "bg-ns-fault", why: "The camera can’t be reached. Reconnecting." };
    default:
      return {
        state: "Stopped",
        tone: "bg-ns-attention",
        why: `Not being captured. Last picture ${formatSeen(view.camera.last_seen_at)}.`,
      };
  }
}

// A live camera's current picture, asked for every few seconds with the ETag of the one shown, so
// an unchanged picture costs a 304 (the wall's own way, OMNI-503).
function LivePicture({ cameraId, name }: { cameraId: number; name: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [at, setAt] = useState<string | null>(null);
  const etag = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let current: string | null = null;
    const load = async () => {
      try {
        const result = await fetchCameraPreview(cameraId, etag.current);
        if (cancelled || result.kind !== "frame") return;
        etag.current = result.etag;
        const next = URL.createObjectURL(result.blob);
        if (current) URL.revokeObjectURL(current);
        current = next;
        setSrc(next);
        setAt(result.lastModified);
      } catch {
        // Non-fatal: the tile keeps the last picture it had.
      }
    };
    void load();
    const id = setInterval(load, PREVIEW_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
      if (current) URL.revokeObjectURL(current);
    };
  }, [cameraId]);

  return (
    <>
      {src ? (
        // An object URL from an authenticated fetch.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={`${name}, live picture`} width={640} height={360} className="h-full w-full object-cover" />
      ) : (
        <span className="text-sm text-ns-muted">Loading the picture…</span>
      )}
      {at && (
        <span className="absolute right-2.5 bottom-2.5 rounded bg-[#0c0f13]/85 px-2 py-0.5 text-xs text-ns-soft">
          {secondsFormat.format(new Date(at))}
        </span>
      )}
    </>
  );
}

function CameraTile({ view, canSeeWall, canSeeCameras }: { view: CameraView; canSeeWall: boolean; canSeeCameras: boolean }) {
  const { camera, live } = view;
  const isLive = camera.status !== "disabled" && live?.state === "live";
  const off = isLive ? null : notLive(view);
  const action =
    camera.status === "disabled"
      ? canSeeCameras && { href: "/cameras", text: "Open cameras" }
      : canSeeWall && { href: "/live", text: "Open live monitoring" };

  return (
    <article className="overflow-hidden rounded-lg border border-ns-line bg-ns-panel">
      <div className="relative flex aspect-video items-center justify-center bg-[#101418]">
        {isLive ? (
          <>
            <LivePicture cameraId={camera.id} name={camera.name} />
            <span className="absolute top-2.5 left-2.5 flex items-center gap-1.5 rounded bg-[#0c0f13]/85 px-2 py-0.5 text-xs font-semibold">
              <span aria-hidden="true" className="size-[7px] rounded-full bg-ns-live motion-safe:animate-ns-breathe" />
              Live
            </span>
            <span aria-hidden="true" className="absolute inset-x-0 bottom-0 h-[3px] bg-ns-live/80" />
          </>
        ) : (
          <div className="px-4 text-center">
            <p className="flex items-center justify-center gap-1.5 text-[13px] font-semibold text-ns-text">
              <span aria-hidden="true" className={`size-[7px] rounded-full ${off?.tone}`} />
              {off?.state}
            </p>
            <p className="mt-1 text-[13px] text-ns-muted">{off?.why}</p>
          </div>
        )}
      </div>
      <div className="flex items-center justify-between gap-3 px-3.5 py-2.5">
        <div className="min-w-0">
          <p className="truncate font-medium">{camera.name}</p>
          <p className="truncate text-[13px] text-ns-muted">{camera.location}</p>
        </div>
        {!isLive && action && (
          <Link href={action.href} className={`${LINK} flex-none`}>
            {action.text}
          </Link>
        )}
      </div>
    </article>
  );
}

// ---- Needs a look ---------------------------------------------------------------------------

type Attention = { key: string; tone: string; title: string; detail: string; href: string | null; action: string };

function needsALook(views: CameraView[], canSeeWall: boolean, canSeeCameras: boolean): Attention[] {
  const items: Attention[] = [];
  for (const view of views) {
    if (view.camera.status === "disabled") continue;
    const state = view.live?.state;
    if (state === "live") continue;
    const off = notLive(view);
    items.push({
      key: `camera-${view.camera.id}`,
      tone: off.tone,
      title: `${view.camera.name} is ${off.state.toLowerCase()}`,
      detail: off.why,
      href: canSeeWall ? "/live" : null,
      action: state === "stopped" || state === undefined ? "Start capture on the wall" : "Open live monitoring",
    });
  }
  const disabled = views.filter((view) => view.camera.status === "disabled");
  if (disabled.length > 0) {
    items.push({
      key: "disabled",
      tone: "bg-ns-muted",
      title: disabled.length === 1 ? "1 camera is disabled" : `${disabled.length} cameras are disabled`,
      detail: `${disabled.map((view) => view.camera.name).join(", ")}.`,
      href: canSeeCameras ? "/cameras" : null,
      action: "Review cameras",
    });
  }
  return items;
}

function NeedsALook({ items }: { items: Attention[] }) {
  return (
    <section aria-labelledby="attention-title" className="min-w-0 flex-[1_1_300px]">
      <h2 id="attention-title" className="mb-3 text-lg font-semibold">
        Needs a look
      </h2>
      <ul className={PANEL}>
        {items.map((item) => (
          <li key={item.key} className="border-b border-ns-line px-4 py-3.5">
            <p className="flex items-center gap-2 font-medium">
              <span aria-hidden="true" className={`size-2 flex-none rounded-full ${item.tone}`} />
              {item.title}
            </p>
            <p className="mt-0.5 ml-4 text-[13px] text-ns-muted">{item.detail}</p>
            {item.href && (
              <Link href={item.href} className={`${LINK} mt-1.5 ml-4 inline-block`}>
                {item.action}
              </Link>
            )}
          </li>
        ))}
        {items.length === 0 && (
          <li className="border-b border-ns-line px-4 py-3.5 text-sm text-ns-soft">
            Nothing needs a look. Every enabled camera is live.
          </li>
        )}
        <li className="px-4 py-3.5 text-sm text-ns-muted">
          Alerts aren’t switched on yet. When they are, they’ll be listed here first.
        </li>
      </ul>
    </section>
  );
}

// ---- The page --------------------------------------------------------------------------------

export default function DashboardPage() {
  const visible = useDocumentVisible();
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The ribbon draws in once, on the first load, not on every refresh.
  const [firstLoad, setFirstLoad] = useState(true);
  const loadedOnce = useRef(false);

  const refresh = useCallback(() => {
    loadSnapshot()
      .then((next) => {
        if (loadedOnce.current) setFirstLoad(false);
        loadedOnce.current = true;
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

  const shell = "min-h-full space-y-6 bg-ns-ground px-8 pt-7 pb-10 text-[15px] leading-normal text-ns-text tabular-nums";

  if (snapshot === null) {
    return (
      <main className={shell}>
        <h1 className="text-2xl leading-tight font-semibold">Dashboard</h1>
        <p role="status" className="text-ns-muted">
          {error ? `The dashboard couldn’t load: ${error}. It will try again in 30 s.` : "Loading…"}
        </p>
      </main>
    );
  }

  const { summary, activity, datasets, cameras, live, coverage, routes, at } = snapshot;
  const canSeeWall = routes.has("/live");
  const canSeeCameras = routes.has("/cameras");
  const canSeeDatasets = routes.has("/datasets");

  const liveById = new Map(live.map((row) => [row.camera_id, row]));
  const views: CameraView[] = cameras.map((camera) => ({ camera, live: liveById.get(camera.id) }));
  const rank = (view: CameraView) =>
    view.camera.status === "disabled" ? 3 : view.live?.state === "live" ? 0 : view.live?.state === "stopped" ? 2 : 1;
  const shown = [...views].sort((a, b) => rank(a) - rank(b) || a.camera.name.localeCompare(b.camera.name)).slice(0, MAX_TILES);
  const notLiveCount = summary.cameras_total - summary.cameras_online;

  const clipsLoaded = datasets?.reduce((sum, d) => sum + d.videos_loaded, 0) ?? 0;
  const searchable = coverage && {
    frames: coverage.reduce((sum, row) => sum + row.frames_embedded, 0),
    total: coverage.reduce((sum, row) => sum + row.frames_total, 0),
  };

  return (
    <main className={shell}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex flex-wrap items-baseline gap-x-3.5">
          <h1 className="text-2xl leading-tight font-semibold">Dashboard</h1>
          <span className="text-ns-muted">{dayFormat.format(at)}</span>
        </div>
        {/* Only a failed refresh is announced; the 30 s "Updated" line would be noise. */}
        <p className="text-[13px] text-ns-muted">
          <span aria-live="polite" className="text-ns-attention">
            {error && `Couldn’t refresh (${error}). Showing ${timeFormat.format(at)}; trying again in 30 s.`}
          </span>
          {!error && <>Updated {timeFormat.format(at)}, refreshes every 30&nbsp;s</>}
        </p>
      </div>

      <Ribbon hours={activity} animate={firstLoad} />

      <section aria-label="System status" className={`${PANEL} flex flex-wrap overflow-hidden`}>
        <Reading
          href={canSeeWall ? "/live" : null}
          label="Cameras live"
          value={number.format(summary.cameras_online)}
          unit={`of ${number.format(summary.cameras_total)}`}
          note={summary.cameras_total === 0 ? "No camera added yet" : notLiveCount > 0 ? `${notLiveCount} not live` : "All live"}
          noteTone={notLiveCount > 0 ? "attention" : "muted"}
        />
        <Reading
          href="/videos"
          label="Footage held"
          value={number.format(summary.videos)}
          unit={summary.videos === 1 ? "video" : "videos"}
          note={datasets ? `including ${number.format(clipsLoaded)} dataset clips` : "recordings, uploads, dataset clips"}
        />
        <Reading
          href="/videos"
          label="Storage"
          value={summary.storage_gb.toFixed(2)}
          unit="GB"
          note={
            summary.oldest_recording_at
              ? `kept ${summary.retention_days} days, oldest ${shortDate.format(new Date(summary.oldest_recording_at))}`
              : `kept ${summary.retention_days} days`
          }
        />
        {searchable && (
          <Reading
            href="/search"
            label="Searchable"
            value={number.format(searchable.frames)}
            unit={`of ${number.format(searchable.total)}`}
            note={
              searchable.frames < searchable.total
                ? "frames, by scene; more as encoding runs"
                : "every kept frame, by scene"
            }
          />
        )}
      </section>

      <div className="flex flex-wrap items-start gap-6">
        <section aria-labelledby="cameras-title" className="min-w-0 flex-[2_1_560px]">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h2 id="cameras-title" className="text-lg font-semibold">
              Cameras
            </h2>
            {canSeeWall && cameras.length > 0 && (
              <Link href="/live" className={LINK}>
                Open the live wall
              </Link>
            )}
          </div>
          {cameras.length === 0 ? (
            <div className={`${PANEL} px-5 py-8 text-center`}>
              <p className="font-medium">No cameras yet</p>
              <p className="mt-1 text-sm text-ns-muted">Add a camera and its picture will appear here.</p>
              {canSeeCameras && (
                <Link href="/cameras" className={`${LINK} mt-3 inline-block`}>
                  Add a camera
                </Link>
              )}
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {shown.map((view) => (
                  <CameraTile key={view.camera.id} view={view} canSeeWall={canSeeWall} canSeeCameras={canSeeCameras} />
                ))}
              </div>
              {cameras.length > shown.length && (
                <p className="mt-3 text-sm text-ns-muted">
                  {cameras.length - shown.length} more on{" "}
                  {canSeeWall ? (
                    <Link href="/live" className={LINK}>
                      the live wall
                    </Link>
                  ) : (
                    "the live wall"
                  )}
                  .
                </p>
              )}
            </>
          )}
        </section>

        <NeedsALook items={needsALook(views, canSeeWall, canSeeCameras)} />
      </div>

      {canSeeDatasets && datasets && datasets.length > 0 && (
        <p className="text-sm text-ns-muted">
          Research footage: {number.format(clipsLoaded)} dataset clips loaded.{" "}
          <Link href="/datasets" className={LINK}>
            Open datasets
          </Link>
        </p>
      )}
    </main>
  );
}
