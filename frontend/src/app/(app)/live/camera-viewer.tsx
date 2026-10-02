"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  type BufferFrame,
  fetchCameraPreview,
  fetchFrameImage,
  getCameraBuffer,
  type LiveCamera,
} from "@/lib/api-client";

// One camera, enlarged (OMNI-508). Its preview is asked for twice as often as on
// the wall: the preview is rewritten at most every 0.5 s (OMNI-503), so this is
// every new picture.
const PREVIEW_POLL_MS = 500;
// How far back Rewind goes: the buffer's default (OMNI-505).
const REWIND_MINUTES = 5;
// Full frames kept in memory while scrubbing, so stepping back and forth over
// the same few seconds does not fetch them again. Older ones are released.
const FRAME_CACHE = 40;

const STATE_LABEL: Record<LiveCamera["state"], string> = {
  live: "Live",
  frozen: "Frozen",
  offline: "Offline",
  stopped: "Stopped",
};

function formatClock(timestampS: number): string {
  return new Date(timestampS * 1000).toLocaleTimeString();
}

// The live picture: the same preview the tile shows, polled every 0.5 s with
// its ETag, so an unchanged picture costs a 304.
function LivePicture({ camera }: { camera: LiveCamera }) {
  const [src, setSrc] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const etag = useRef<string | null>(null);
  const shown = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    async function poll() {
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
          setProblem(null);
        } else if (result.kind === "none") {
          etag.current = null;
          setProblem(result.reason);
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
      if (shown.current) URL.revokeObjectURL(shown.current);
      shown.current = null;
    };
  }, [camera.camera_id]);

  if (!src) {
    return (
      <div className="flex h-full w-full items-center justify-center text-sm text-zinc-300">
        {problem ?? "Waiting for the picture…"}
      </div>
    );
  }
  return (
    // An object URL from an authenticated fetch.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={`Current frame from ${camera.name}`}
      className={`h-full w-full object-contain ${camera.state === "live" ? "" : "opacity-40 grayscale"}`}
    />
  );
}

// The scrubber's track: one tick per stored frame, placed by its capture time
// across the window, so the gaps between frames show as gaps. Motion frames
// stand tall and coloured; heartbeat frames (kept only because a second passed)
// are short and grey.
function ScrubberTrack({
  frames,
  index,
  start,
  end,
  onPick,
}: {
  frames: BufferFrame[];
  index: number;
  start: number;
  end: number;
  onPick: (index: number) => void;
}) {
  const span = Math.max(end - start, 1);
  const position = (t: number) => `${((t - start) / span) * 100}%`;
  const current = frames[index];

  function pickAt(event: React.MouseEvent<HTMLDivElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const t = start + ((event.clientX - box.left) / box.width) * span;
    let best = 0;
    for (let i = 1; i < frames.length; i += 1) {
      if (Math.abs(frames[i].timestamp_s - t) < Math.abs(frames[best].timestamp_s - t)) best = i;
    }
    onPick(best);
  }

  return (
    <div
      className="relative h-10 w-full cursor-pointer rounded-md bg-zinc-800"
      onClick={pickAt}
      role="presentation"
    >
      {frames.map((frame) => (
        <span
          key={frame.segment_id}
          data-reason={frame.reason}
          className={`absolute bottom-1 w-px ${
            frame.reason === "motion" ? "top-1 bg-amber-400" : "top-6 bg-zinc-500"
          }`}
          style={{ left: position(frame.timestamp_s) }}
        />
      ))}
      {current && (
        <span
          className="pointer-events-none absolute -bottom-1 -top-1 w-0.5 -translate-x-1/2 rounded bg-white shadow"
          style={{ left: position(current.timestamp_s) }}
        />
      )}
    </div>
  );
}

// Rewind: the last few minutes of the camera's stored frames (OMNI-505), one at
// a time. A flip-book of the frames the gate kept, not video.
function Rewind({ camera, onBack }: { camera: LiveCamera; onBack: () => void }) {
  const [frames, setFrames] = useState<BufferFrame[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [src, setSrc] = useState<string | null>(null);
  const cache = useRef(new Map<number, string>());

  useEffect(() => {
    let cancelled = false;
    getCameraBuffer(camera.camera_id, REWIND_MINUTES)
      .then((next) => {
        if (cancelled) return;
        setFrames(next);
        setIndex(Math.max(0, next.length - 1)); // start at the newest, and step back
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not load the last minutes.");
      });
    const kept = cache.current;
    return () => {
      cancelled = true;
      for (const url of kept.values()) URL.revokeObjectURL(url);
      kept.clear();
    };
  }, [camera.camera_id]);

  const load = useCallback(async (frame: BufferFrame): Promise<string> => {
    const kept = cache.current;
    const hit = kept.get(frame.segment_id);
    if (hit) {
      kept.delete(frame.segment_id); // re-insert: most recently used last
      kept.set(frame.segment_id, hit);
      return hit;
    }
    const url = URL.createObjectURL(await fetchFrameImage(frame.frame_url));
    kept.set(frame.segment_id, url);
    while (kept.size > FRAME_CACHE) {
      const [oldest, oldUrl] = kept.entries().next().value as [number, string];
      kept.delete(oldest);
      URL.revokeObjectURL(oldUrl);
    }
    return url;
  }, []);

  const frame = frames?.[index] ?? null;

  useEffect(() => {
    if (!frame || !frames) return;
    let cancelled = false;
    load(frame)
      .then((url) => {
        if (!cancelled) setSrc(url);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load this frame.");
      });
    // The next frames back and forward, so stepping does not wait.
    for (const near of [frames[index - 1], frames[index + 1]]) {
      if (near) load(near).catch(() => undefined);
    }
    return () => {
      cancelled = true;
    };
  }, [frame, frames, index, load]);

  const step = useCallback(
    (by: number) => setIndex((i) => (frames ? Math.min(frames.length - 1, Math.max(0, i + by)) : i)),
    [frames],
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "ArrowLeft") step(event.shiftKey ? -10 : -1);
      if (event.key === "ArrowRight") step(event.shiftKey ? 10 : 1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step]);

  const motion = useMemo(() => frames?.filter((f) => f.reason === "motion").length ?? 0, [frames]);

  if (error && !frames) return <p className="p-6 text-sm text-red-300">{error}</p>;
  if (!frames) return <p className="p-6 text-sm text-zinc-300">Loading the last {REWIND_MINUTES} minutes…</p>;
  if (frames.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-zinc-300">
        <p>No frames stored in the last {REWIND_MINUTES} minutes.</p>
        <button type="button" onClick={onBack} className="rounded-lg bg-white/10 px-3 py-1.5 hover:bg-white/20">
          Back to live
        </button>
      </div>
    );
  }

  const start = frames[0].timestamp_s;
  const end = frames[frames.length - 1].timestamp_s;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative min-h-0 flex-1 bg-black">
        {src && (
          // An object URL from an authenticated fetch.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt={`Frame at ${formatClock(frame!.timestamp_s)}`} className="h-full w-full object-contain" />
        )}
        <span className="absolute left-3 top-3 rounded-md bg-black/70 px-2 py-1 text-xs font-semibold text-zinc-100">
          Rewind · {formatClock(frame!.timestamp_s)} ·{" "}
          <span className={frame!.reason === "motion" ? "text-amber-300" : "text-zinc-300"}>
            {frame!.reason === "motion" ? "motion" : "heartbeat"}
          </span>
        </span>
      </div>

      <ScrubberTrack frames={frames} index={index} start={start} end={end} onPick={setIndex} />
      <input
        type="range"
        min={0}
        max={frames.length - 1}
        value={index}
        onChange={(event) => setIndex(Number(event.target.value))}
        aria-label="Frame"
        className="w-full accent-amber-400"
      />

      <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-zinc-300">
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => step(-1)} disabled={index === 0}
            className="rounded-lg bg-white/10 px-3 py-1.5 hover:bg-white/20 disabled:opacity-40">
            ← Previous
          </button>
          <button type="button" onClick={() => step(1)} disabled={index === frames.length - 1}
            className="rounded-lg bg-white/10 px-3 py-1.5 hover:bg-white/20 disabled:opacity-40">
            Next →
          </button>
          <span className="tabular-nums">
            Frame {index + 1} of {frames.length}
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-px bg-amber-400" /> motion ({motion})
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-px bg-zinc-500" /> heartbeat ({frames.length - motion})
          </span>
          <span>
            {formatClock(start)} – {formatClock(end)}
          </span>
        </div>
        <button type="button" onClick={onBack}
          className="rounded-lg bg-white px-3 py-1.5 font-medium text-black hover:bg-zinc-200">
          Back to live
        </button>
      </div>
    </div>
  );
}

// The enlarged view (OMNI-508): over the whole window, and the browser's full
// screen when it allows it. Esc closes it (in full screen the browser leaves
// full screen on Esc first, and that closes it too).
export function CameraViewer({ camera, onClose }: { camera: LiveCamera; onClose: () => void }) {
  const [rewinding, setRewinding] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  // The latest onClose, without re-running the effect below (which would ask
  // for full screen again) every time the page re-renders.
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const element = root.current;
    // Allowed here because opening the view is the user's click.
    element?.requestFullscreen?.().catch(() => undefined);
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") close.current();
    }
    function onFullscreenChange() {
      if (!document.fullscreenElement) close.current();
    }
    window.addEventListener("keydown", onKey);
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("fullscreenchange", onFullscreenChange);
      if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    };
  }, []);

  return (
    <div
      ref={root}
      role="dialog"
      aria-modal="true"
      aria-label={`${camera.name}, enlarged`}
      className="fixed inset-0 z-50 flex flex-col gap-3 bg-zinc-950 p-4 text-zinc-100"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-base font-semibold">{camera.name}</p>
          <p className="truncate text-xs text-zinc-400">
            {camera.location} · {STATE_LABEL[camera.state]}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!rewinding && (
            <button type="button" onClick={() => setRewinding(true)}
              className="rounded-lg bg-amber-400 px-3 py-1.5 text-sm font-medium text-black hover:bg-amber-300">
              Rewind
            </button>
          )}
          <button type="button" onClick={onClose} aria-label="Close"
            className="rounded-lg bg-white/10 px-3 py-1.5 text-sm hover:bg-white/20">
            Close (Esc)
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {rewinding ? (
          <Rewind camera={camera} onBack={() => setRewinding(false)} />
        ) : (
          <div className="h-full bg-black">
            <LivePicture camera={camera} />
          </div>
        )}
      </div>
    </div>
  );
}
