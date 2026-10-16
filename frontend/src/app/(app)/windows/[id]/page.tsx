"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  type EventWindow,
  type EventWindowDetail,
  getWindow,
  listSampleWindows,
  setWindowVerdict,
} from "@/lib/api-client";
import { DATASET_LABELS, SOURCE_LABELS, WRONG_REASONS, formatSeconds } from "@/lib/windows";

// One lead-up window, checked by eye (OMNI-609, criterion D-27). The player plays the
// window and a little past it; the timeline shades the window and marks the annotated
// event, so the boundary between them is what the eye judges.

// "A little past it": enough to see the event begin, short enough to stay on the boundary.
const PAST_EVENT_S = 4;
// Jump to just before the boundary, to look at it closely.
const BEFORE_BOUNDARY_S = 3;

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function WindowTimeline({
  window,
  durationS,
  currentS,
  onSeek,
}: {
  window: EventWindowDetail;
  durationS: number;
  currentS: number;
  onSeek: (s: number) => void;
}) {
  const pct = (s: number) => `${Math.min(100, Math.max(0, (s / durationS) * 100))}%`;
  const eventEnd = window.event_end_s ?? window.event_start_s;
  return (
    <div className="space-y-2">
      <div
        className="relative h-6 w-full cursor-pointer overflow-hidden rounded-md bg-zinc-100 dark:bg-zinc-800"
        onClick={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          onSeek(((e.clientX - box.left) / box.width) * durationS);
        }}
      >
        <div
          title="Lead-up window"
          className="absolute top-0 h-full bg-indigo-500/40"
          style={{ left: pct(window.window_start_s), width: pct(window.window_end_s - window.window_start_s) }}
        />
        <div
          title="Annotated event"
          className="absolute top-0 h-full bg-red-500/50"
          style={{ left: pct(window.event_start_s), width: pct(Math.max(eventEnd - window.event_start_s, durationS / 400)) }}
        />
        <div className="absolute top-0 h-full w-[2px] bg-zinc-900 dark:bg-white" style={{ left: pct(currentS) }} />
      </div>
      <div className="flex flex-wrap items-center gap-4 text-xs text-zinc-500 dark:text-zinc-400">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-3 rounded-sm bg-indigo-500/60" /> Window {formatSeconds(window.window_start_s)}–
          {formatSeconds(window.window_end_s)}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-3 rounded-sm bg-red-500/70" /> Event from {formatSeconds(window.event_start_s)}
          {window.event_end_s !== null && ` to ${formatSeconds(window.event_end_s)}`}
        </span>
        <span className="ml-auto tabular-nums">
          {formatSeconds(currentS)} / {formatSeconds(durationS)}
        </span>
      </div>
    </div>
  );
}

function VerdictPanel({
  window,
  onSaved,
}: {
  window: EventWindowDetail;
  onSaved: (updated: EventWindowDetail) => void;
}) {
  const [reason, setReason] = useState<string>(WRONG_REASONS[0]);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(correct: boolean) {
    setSaving(true);
    setError(null);
    try {
      const text = note.trim() ? `${reason}: ${note.trim()}` : reason;
      onSaved(await setWindowVerdict(window.id, correct, correct ? null : text));
      setNote("");
    } catch (err) {
      setError(errorMessage(err, "could not save the verdict"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3 rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
      <p className="text-sm text-zinc-700 dark:text-zinc-300">
        <strong>Correct</strong> when the window ends where the event visibly begins (within 1.5 s) and shows none of
        the event.
      </p>
      {window.verified !== null && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Current verdict: <strong>{window.verified ? "Correct" : `Wrong (${window.verify_reason})`}</strong>
          {window.verified_by && ` by ${window.verified_by}`}
          {window.verified_at && `, ${new Date(window.verified_at).toLocaleString()}`}
        </p>
      )}
      <div className="flex flex-wrap items-end gap-3">
        <button
          type="button"
          disabled={saving}
          onClick={() => save(true)}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          Verified
        </button>
        <div className="flex flex-wrap items-end gap-2">
          <select
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="rounded-lg border border-zinc-300 bg-white px-2 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          >
            {WRONG_REASONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What you saw (optional), e.g. robbery visible at 1:12"
            maxLength={400}
            className="w-72 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          />
          <button
            type="button"
            disabled={saving}
            onClick={() => save(false)}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
          >
            Wrong
          </button>
        </div>
      </div>
      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}

export default function WindowCheckPage() {
  const params = useParams<{ id: string }>();
  const windowId = Number(params.id);

  const [detail, setDetail] = useState<EventWindowDetail | null>(null);
  const [all, setAll] = useState<EventWindow[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [currentS, setCurrentS] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);
  const stopAtRef = useRef<number | null>(null);

  useEffect(() => {
    getWindow(windowId)
      .then(setDetail)
      .catch((err) => setLoadError(errorMessage(err, "could not load this window")));
    listSampleWindows()
      .then(setAll)
      .catch(() => {
        // Non-fatal: only the next / previous links need it.
      });
  }, [windowId]);

  function playFrom(start: number, stop: number) {
    const v = videoRef.current;
    if (!v) return;
    stopAtRef.current = stop;
    v.currentTime = Math.max(0, start);
    void v.play();
  }

  function seek(s: number) {
    stopAtRef.current = null;
    if (videoRef.current) videoRef.current.currentTime = s;
  }

  function onTimeUpdate() {
    const v = videoRef.current;
    if (!v) return;
    setCurrentS(v.currentTime);
    if (stopAtRef.current !== null && v.currentTime >= stopAtRef.current) {
      v.pause();
      stopAtRef.current = null;
    }
  }

  // Moving to another window reuses this page: until the new one arrives, show nothing stale.
  const shown = detail !== null && detail.id === windowId ? detail : null;
  const index = all.findIndex((w) => w.id === windowId);
  const prev = index > 0 ? all[index - 1] : null;
  const next = index >= 0 && index < all.length - 1 ? all[index + 1] : null;
  const nextUnchecked = all.find((w, i) => i > index && w.verified === null) ?? all.find((w) => w.verified === null && w.id !== windowId);

  function saved(updated: EventWindowDetail) {
    setDetail(updated);
    setAll((list) => list.map((w) => (w.id === updated.id ? { ...w, ...updated } : w)));
  }

  return (
    <main className="space-y-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <Link href="/windows" className="text-zinc-500 hover:underline dark:text-zinc-400">
          ← All sampled windows
        </Link>
        <div className="flex items-center gap-3">
          {index >= 0 && (
            <span className="text-zinc-400">
              {index + 1} of {all.length}
            </span>
          )}
          {prev && (
            <Link href={`/windows/${prev.id}`} className="text-zinc-500 hover:underline dark:text-zinc-400">
              ← Previous
            </Link>
          )}
          {next && (
            <Link href={`/windows/${next.id}`} className="text-zinc-500 hover:underline dark:text-zinc-400">
              Next →
            </Link>
          )}
          {nextUnchecked && (
            <Link
              href={`/windows/${nextUnchecked.id}`}
              className="rounded-lg bg-zinc-900 px-3 py-1.5 font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900"
            >
              Next unchecked →
            </Link>
          )}
        </div>
      </div>

      {loadError && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
          {loadError}
        </p>
      )}

      {shown === null ? (
        !loadError && <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading window…</p>
      ) : (
        <div className="space-y-4">
          <div>
            <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">{shown.clip_key}</h1>
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              {DATASET_LABELS[shown.dataset]} · {shown.event_class} · {shown.split} · event time from{" "}
              {SOURCE_LABELS[shown.annotation_source]} · window {shown.length_s.toFixed(1)} s
              {shown.nominal_length_s !== null && ` of ${shown.nominal_length_s} s`}
              {shown.shortened && " (shortened: the video starts less than that before the event)"}
            </p>
          </div>

          {shown.playback_url === null || shown.video_duration_s === null ? (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              This clip is not loaded into the product, so it cannot be played here.
            </p>
          ) : (
            <>
              <div className="overflow-hidden rounded-2xl border border-zinc-200 bg-black dark:border-zinc-800">
                <video
                  ref={videoRef}
                  src={shown.playback_url}
                  controls
                  onTimeUpdate={onTimeUpdate}
                  className="aspect-video w-full"
                />
              </div>
              <WindowTimeline window={shown} durationS={shown.video_duration_s} currentS={currentS} onSeek={seek} />
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => playFrom(shown.window_start_s, shown.event_start_s + PAST_EVENT_S)}
                  className="rounded-lg border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
                >
                  ▶ Play window (+{PAST_EVENT_S} s past the event start)
                </button>
                <button
                  type="button"
                  onClick={() =>
                    playFrom(shown.window_end_s - BEFORE_BOUNDARY_S, shown.event_start_s + PAST_EVENT_S)
                  }
                  className="rounded-lg border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
                >
                  ▶ Play the boundary ({BEFORE_BOUNDARY_S} s before the window ends)
                </button>
              </div>
            </>
          )}

          <VerdictPanel key={shown.id} window={shown} onSaved={saved} />
        </div>
      )}
    </main>
  );
}
