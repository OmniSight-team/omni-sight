"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  type Frame,
  type FrameFilter,
  type Video,
  type VideoStatus,
  getVideo,
  listAllFrames,
  regateVideo,
} from "@/lib/api-client";

const STATUS_STYLES: Record<VideoStatus, string> = {
  uploaded: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  extracting: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
  ready: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
  failed: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400",
};

function StatusBadge({ status }: { status: VideoStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_STYLES[status]}`}
    >
      {status}
    </span>
  );
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

// mm:ss.t — tenths matter here because clicking a thumbnail has to land the
// player on that exact frame, not just "somewhere in the right second".
function formatTimestamp(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(1).padStart(4, "0");
  return `${mins}:${secs}`;
}

// Motion and heartbeat get different colors on the timeline and grid — "the
// shape of the activity visible at a glance" is more informative when it
// also shows which admissions are the recording's own real motion versus
// the fixed schedule (OMNI-305) that fires when nothing else does.
const REASON_STYLES: Record<string, string> = {
  motion: "bg-indigo-600",
  heartbeat: "bg-amber-500",
};

function Timeline({ durationS, frames }: { durationS: number; frames: Frame[] }) {
  return (
    <div className="space-y-2">
      <div className="relative h-3 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
        {frames.map((frame) => (
          <div
            key={frame.segment_id}
            title={`${frame.timestamp_s.toFixed(2)}s — ${frame.admission_reason ?? "admitted"}`}
            className={`absolute top-0 h-full w-[3px] ${
              REASON_STYLES[frame.admission_reason ?? ""] ?? "bg-indigo-600"
            }`}
            style={{ left: `${Math.min(99.6, (frame.timestamp_s / durationS) * 100)}%` }}
          />
        ))}
      </div>
      <div className="flex items-center gap-4 text-xs text-zinc-500 dark:text-zinc-400">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-indigo-600" /> Motion
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-amber-500" /> Heartbeat
        </span>
        <span className="ml-auto">
          {frames.length} admitted frame{frames.length === 1 ? "" : "s"}
        </span>
      </div>
    </div>
  );
}

const GRID_FILTERS: { value: FrameFilter; label: string }[] = [
  { value: "admitted", label: "Admitted" },
  { value: "discarded", label: "Discarded" },
  { value: "all", label: "All" },
];

function FrameFilterTabs({
  value,
  onChange,
}: {
  value: FrameFilter;
  onChange: (filter: FrameFilter) => void;
}) {
  return (
    <div className="inline-flex rounded-lg border border-zinc-200 p-0.5 dark:border-zinc-800">
      {GRID_FILTERS.map((filter) => (
        <button
          key={filter.value}
          type="button"
          onClick={() => onChange(filter.value)}
          className={`rounded-md px-3 py-1 text-xs font-medium transition ${
            value === filter.value
              ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
              : "text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          }`}
        >
          {filter.label}
        </button>
      ))}
    </div>
  );
}

// Per-cell motion bar (mean grayscale difference, 0-255). Lower admits more.
// Capped at 60: on the test clip everything from 50 up admits the same nine
// heartbeat frames, so a wider range would spend half the slider on no change.
const THRESHOLD_MIN = 1;
const THRESHOLD_MAX = 60;

function ThresholdSlider({
  value,
  busy,
  error,
  onChange,
}: {
  value: number;
  busy: boolean;
  error: string | null;
  onChange: (value: number) => void;
}) {
  // A recording gated outside the slider's range (through the API) still
  // shows a position and number the slider can actually hold.
  const shown = Math.min(THRESHOLD_MAX, Math.max(THRESHOLD_MIN, value));
  return (
    <div className="space-y-1">
      <label className="flex items-center gap-3 text-xs text-zinc-500 dark:text-zinc-400">
        <span className="whitespace-nowrap">Motion threshold</span>
        <input
          type="range"
          min={THRESHOLD_MIN}
          max={THRESHOLD_MAX}
          step={1}
          value={shown}
          onChange={(event) => onChange(Number(event.target.value))}
          className="h-1.5 w-full max-w-xs cursor-pointer accent-indigo-600"
        />
        <span className="w-8 font-medium tabular-nums text-zinc-900 dark:text-zinc-50">{shown}</span>
        <span className="w-24 text-zinc-400 dark:text-zinc-500">{busy ? "Recomputing…" : ""}</span>
      </label>
      <p className="text-[11px] text-zinc-400 dark:text-zinc-500">
        Lower admits more frames. Applies to this recording only — the default threshold in settings is
        not changed.
      </p>
      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}

function FrameCounts({ total, kept, discarded }: { total: number; kept: number; discarded: number }) {
  const pctRetained = total > 0 ? Math.round((kept / total) * 100) : 0;
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-zinc-500 dark:text-zinc-400">
      <span>{kept} kept</span>
      <span>{discarded} discarded</span>
      <span>{pctRetained}% retained</span>
    </div>
  );
}

function FrameTile({
  frame,
  thumbVersion,
  onSeek,
}: {
  frame: Frame;
  thumbVersion: number;
  onSeek: (timestampS: number) => void;
}) {
  const reasonDot = frame.admitted
    ? (REASON_STYLES[frame.admission_reason ?? ""] ?? "bg-indigo-600")
    : null;

  return (
    <button
      type="button"
      onClick={() => onSeek(frame.timestamp_s)}
      title={`Seek to ${formatTimestamp(frame.timestamp_s)}`}
      className={`group flex flex-col overflow-hidden rounded-lg border text-left transition hover:ring-2 hover:ring-indigo-500 ${
        frame.admitted
          ? "border-zinc-200 dark:border-zinc-800"
          : "border-dashed border-zinc-300 opacity-60 hover:opacity-100 dark:border-zinc-700"
      }`}
    >
      <div className="relative aspect-video w-full bg-zinc-100 dark:bg-zinc-800">
        {frame.thumb_url ? (
          // Thumbnails are served directly by nginx (OMNI-307), not through Next's image optimizer.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={`${frame.thumb_url}?v=${thumbVersion}`}
            alt={`Frame at ${formatTimestamp(frame.timestamp_s)}`}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-[11px] text-zinc-400 dark:text-zinc-500">
            discarded
          </div>
        )}
        {reasonDot && <span className={`absolute left-1 top-1 h-2 w-2 rounded-full ${reasonDot}`} />}
      </div>
      <div className="flex items-center justify-between px-1.5 py-1 text-[11px] text-zinc-500 dark:text-zinc-400">
        <span>{formatTimestamp(frame.timestamp_s)}</span>
        <span>{frame.motion_score != null ? frame.motion_score.toFixed(3) : "—"}</span>
      </div>
    </button>
  );
}

function FrameGrid({
  frames,
  thumbVersion,
  onSeek,
}: {
  frames: Frame[];
  thumbVersion: number;
  onSeek: (timestampS: number) => void;
}) {
  if (frames.length === 0) {
    return <p className="text-sm text-zinc-500 dark:text-zinc-400">No frames match this filter.</p>;
  }
  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
      {frames.map((frame) => (
        <FrameTile key={frame.segment_id} frame={frame} thumbVersion={thumbVersion} onSeek={onSeek} />
      ))}
    </div>
  );
}

export default function VideoPlayerPage() {
  const params = useParams<{ id: string }>();
  const videoId = Number(params.id);

  const [video, setVideo] = useState<Video | null>(null);
  const [allFrames, setAllFrames] = useState<Frame[]>([]);
  const [gridFilter, setGridFilter] = useState<FrameFilter>("admitted");
  const [loadError, setLoadError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  // The slider position, and the re-gate loop that follows it. The server
  // refuses a second gate while one is running, so the loop is single-flight
  // and latest-wins: while a run is in flight, further drags only update
  // `wantedRef`; when the run ends, one more run goes out for the newest value.
  const [threshold, setThreshold] = useState<number | null>(null);
  const [regating, setRegating] = useState(false);
  const [regateError, setRegateError] = useState<string | null>(null);
  // Every re-gate wipes and rewrites the thumbnails folder, so a tile that
  // asked for its image mid-rewrite gets a 404 and, with an unchanged src,
  // never asks again. A new version per finished re-gate changes every URL, so
  // the last state shown always reloads its images after the rewrite is done.
  const [thumbVersion, setThumbVersion] = useState(0);
  const appliedRef = useRef<number | null>(null);
  const wantedRef = useRef<number | null>(null);
  const runningRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    getVideo(videoId)
      .then((loaded) => {
        setVideo(loaded);
        setThreshold(loaded.gate_cell_threshold);
        appliedRef.current = loaded.gate_cell_threshold;
        wantedRef.current = loaded.gate_cell_threshold;
      })
      .catch((err) => setLoadError(errorMessage(err, "could not load this recording")));
    // Fetches the whole set once — the timeline, the grid's own filter
    // toggle, and the kept/discarded counts all derive from this same array
    // client-side, so counts stay exact and switching the grid filter is
    // instant instead of round-tripping to the API on every click.
    listAllFrames(videoId, "all")
      .then(setAllFrames)
      .catch(() => {
        // Non-fatal — the player still works, just without timeline marks or a frame grid.
      });
  }, [videoId]);

  const admittedFrames = useMemo(() => allFrames.filter((frame) => frame.admitted), [allFrames]);
  const gridFrames = useMemo(() => {
    if (gridFilter === "all") return allFrames;
    const wantAdmitted = gridFilter === "admitted";
    return allFrames.filter((frame) => frame.admitted === wantAdmitted);
  }, [allFrames, gridFilter]);

  async function drainRegates() {
    if (runningRef.current) return;
    runningRef.current = true;
    setRegating(true);
    try {
      while (wantedRef.current !== null && wantedRef.current !== appliedRef.current) {
        const target = wantedRef.current;
        await regateVideo(videoId, target);
        appliedRef.current = target;
        const frames = await listAllFrames(videoId, "all");
        if (!mountedRef.current) return;
        // One state update feeds the timeline, the counts and the grid, so
        // they always change together.
        setAllFrames(frames);
        setThumbVersion((version) => version + 1);
        setRegateError(null);
      }
    } catch (err) {
      wantedRef.current = appliedRef.current;
      if (mountedRef.current) {
        setThreshold(appliedRef.current);
        setRegateError(errorMessage(err, "could not re-run the motion gate"));
      }
    } finally {
      runningRef.current = false;
      if (mountedRef.current) setRegating(false);
    }
  }

  function changeThreshold(value: number) {
    setThreshold(value);
    wantedRef.current = value;
    void drainRegates();
  }

  function seekTo(timestampS: number) {
    if (videoRef.current) {
      videoRef.current.currentTime = timestampS;
    }
  }

  return (
    <main className="p-6">
      <Link
        href="/videos"
        className="mb-4 inline-block text-sm text-zinc-500 hover:underline dark:text-zinc-400"
      >
        ← Video Archive
      </Link>

      {loadError && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
          {loadError}
        </p>
      )}

      {video === null ? (
        !loadError && <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading recording…</p>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <h1 className="truncate text-lg font-semibold text-zinc-900 dark:text-zinc-50">
              {video.filename}
            </h1>
            <StatusBadge status={video.status} />
          </div>

          <div className="overflow-hidden rounded-2xl border border-zinc-200 bg-black dark:border-zinc-800">
            <video ref={videoRef} src={video.playback_url} controls className="aspect-video w-full" />
          </div>

          {video.duration_s == null ? (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              Duration unknown — the timeline needs a successful probe first.
            </p>
          ) : (
            <Timeline durationS={video.duration_s} frames={admittedFrames} />
          )}

          {video.status === "ready" && video.segments_count === 0 && (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              This recording has not been extracted yet — no frames to show on the timeline.
            </p>
          )}

          {video.segments_count > 0 && (
            <div className="space-y-3 border-t border-zinc-200 pt-4 dark:border-zinc-800">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Frames</h2>
                <FrameFilterTabs value={gridFilter} onChange={setGridFilter} />
              </div>
              {threshold !== null && (
                <ThresholdSlider
                  value={threshold}
                  busy={regating}
                  error={regateError}
                  onChange={changeThreshold}
                />
              )}
              <FrameCounts
                total={allFrames.length}
                kept={admittedFrames.length}
                discarded={allFrames.length - admittedFrames.length}
              />
              <FrameGrid frames={gridFrames} thumbVersion={thumbVersion} onSeek={seekTo} />
            </div>
          )}
        </div>
      )}
    </main>
  );
}
