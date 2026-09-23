"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  ApiError,
  type Frame,
  type Video,
  type VideoStatus,
  getVideo,
  listAdmittedFrames,
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

// Motion and heartbeat get different colors on the timeline — "the shape of
// the activity visible at a glance" is more informative when it also shows
// which admissions are the recording's own real motion versus the fixed
// schedule (OMNI-305) that fires when nothing else does.
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

export default function VideoPlayerPage() {
  const params = useParams<{ id: string }>();
  const videoId = Number(params.id);

  const [video, setVideo] = useState<Video | null>(null);
  const [frames, setFrames] = useState<Frame[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    getVideo(videoId)
      .then(setVideo)
      .catch((err) => setLoadError(errorMessage(err, "could not load this recording")));
    listAdmittedFrames(videoId)
      .then(setFrames)
      .catch(() => {
        // Non-fatal — the player still works, just without timeline marks.
      });
  }, [videoId]);

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
            <video src={video.playback_url} controls className="aspect-video w-full" />
          </div>

          {video.duration_s == null ? (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              Duration unknown — the timeline needs a successful probe first.
            </p>
          ) : (
            <Timeline durationS={video.duration_s} frames={frames} />
          )}

          {video.status === "ready" && video.segments_count === 0 && (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              This recording has not been extracted yet — no frames to show on the timeline.
            </p>
          )}
        </div>
      )}
    </main>
  );
}
