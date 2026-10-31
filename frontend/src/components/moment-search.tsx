"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import {
  ApiError,
  type MatchedBy,
  type SearchHit,
  type SearchMode,
  type SearchResponse,
  type SearchScope,
  getEmbeddingStatus,
  searchMoments,
} from "@/lib/api-client";

// Natural-language search inside one video or one camera's frames (OMNI-712, FR-4, D-39).
// The search itself runs inside the vector search, on that footage only.

const MODES: { value: SearchMode; label: string }[] = [
  { value: "frame", label: "Scene" },
  { value: "clip", label: "Action" },
  { value: "fused", label: "Combined" },
];

const MATCHED_BY: Record<MatchedBy, string> = {
  frame: "Scene",
  clip: "Action",
  both: "Scene + action",
};

// `ENCODER_UNAVAILABLE` in services/query/app/search.py: every other 503 there means something else.
const ENCODER_UNAVAILABLE = "the text encoder (ai_workers) is unreachable";

// How often the "searchable so far" line is refreshed while frames are still being encoded.
const STATUS_POLL_MS = 10_000;

type Coverage = { total: number; frames: number; clips: number };

// The date filters are the viewer's own days, the same days the results are shown in.
function dayStart(day: string): string {
  return new Date(`${day}T00:00:00`).toISOString();
}

function dayEnd(day: string): string {
  return new Date(`${day}T23:59:59.999`).toISOString();
}

function formatPosition(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(1).padStart(4, "0");
  return `${mins}:${secs}`;
}

function Notice({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-200 px-4 py-6 text-center dark:border-zinc-800">
      <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">{title}</p>
      <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{children}</p>
    </div>
  );
}

function HitCard({ hit, onPick }: { hit: SearchHit; onPick: (hit: SearchHit) => void }) {
  return (
    <button
      type="button"
      onClick={() => onPick(hit)}
      className="block overflow-hidden rounded-lg border border-zinc-200 text-left transition hover:ring-2 hover:ring-indigo-500 dark:border-zinc-800"
    >
      <div className="aspect-video w-full bg-zinc-100 dark:bg-zinc-800">
        {hit.thumb_url && (
          // Thumbnails are served directly by nginx (OMNI-307), not through Next's image optimizer.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={hit.thumb_url} alt="Matching frame" className="h-full w-full object-cover" />
        )}
      </div>
      <div className="space-y-1 px-2 py-2 text-xs text-zinc-500 dark:text-zinc-400">
        <p className="font-medium tabular-nums text-zinc-900 dark:text-zinc-50">
          {hit.video_id === null ? new Date(hit.captured_at).toLocaleString() : `At ${formatPosition(hit.timestamp_s)}`}
        </p>
        <div className="flex items-center justify-between gap-2">
          <span className="rounded-full bg-indigo-50 px-2 py-0.5 font-medium text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300">
            {MATCHED_BY[hit.matched_by]}
          </span>
          <span className="tabular-nums" title="Score">
            {hit.score.toFixed(4)}
          </span>
        </div>
      </div>
    </button>
  );
}

function hasVectors(mode: SearchMode, coverage: Coverage | null): boolean {
  if (coverage === null) return true;
  if (mode === "frame") return coverage.frames > 0;
  if (mode === "clip") return coverage.clips > 0;
  return coverage.frames > 0 || coverage.clips > 0;
}

export function MomentSearch({
  scope,
  withDates = false,
  onPick,
}: {
  scope: SearchScope;
  withDates?: boolean;
  onPick: (hit: SearchHit) => void;
}) {
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<SearchMode>("fused");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [query, setQuery] = useState("");
  const [running, setRunning] = useState(false);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  // Only the newest search may show its answer: an older, slower one is ignored.
  const latest = useRef(0);
  const scopeKey = JSON.stringify(scope);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function refresh() {
      try {
        const rows = await getEmbeddingStatus(JSON.parse(scopeKey) as SearchScope);
        if (cancelled) return;
        const next = {
          total: rows.reduce((sum, row) => sum + row.frames_total, 0),
          frames: rows.reduce((sum, row) => sum + row.frames_embedded, 0),
          clips: rows.reduce((sum, row) => sum + row.clips_embedded, 0),
        };
        setCoverage(next);
        if (next.frames < next.total || next.total === 0) timer = setTimeout(refresh, STATUS_POLL_MS);
      } catch {
        // Non-fatal: the search still works, without the "searchable so far" line.
      }
    }
    void refresh();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [scopeKey]);

  async function run(text: string, nextMode: SearchMode, nextFrom: string, nextTo: string) {
    if (!text) return;
    const ticket = ++latest.current;
    setQuery(text);
    setRunning(true);
    try {
      const answer = await searchMoments({
        q: text,
        mode: nextMode,
        ...(JSON.parse(scopeKey) as SearchScope),
        from: nextFrom ? dayStart(nextFrom) : undefined,
        to: nextTo ? dayEnd(nextTo) : undefined,
      });
      if (ticket !== latest.current) return;
      setResponse(answer);
      setError(null);
    } catch (err) {
      if (ticket !== latest.current) return;
      setResponse(null);
      setError(err instanceof Error ? err : new Error("could not run this search"));
    } finally {
      if (ticket === latest.current) setRunning(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void run(draft.trim(), mode, from, to);
  }

  const input = "rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50";

  return (
    <section className="space-y-3 border-t border-zinc-200 pt-4 dark:border-zinc-800">
      <form onSubmit={submit} className="flex gap-2">
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="a person opening the trunk of a car"
          maxLength={1000}
          aria-label="Describe what you are looking for"
          className="min-w-0 flex-1 rounded-xl border border-zinc-300 bg-white px-4 py-2.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        />
        <button
          type="submit"
          disabled={!draft.trim()}
          className="rounded-xl bg-zinc-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          Search
        </button>
      </form>

      <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-500 dark:text-zinc-400">
        <div className="inline-flex rounded-lg border border-zinc-200 p-0.5 dark:border-zinc-800">
          {MODES.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={mode === option.value}
              onClick={() => {
                setMode(option.value);
                void run(query, option.value, from, to);
              }}
              className={`rounded-md px-3 py-1 font-medium transition ${
                mode === option.value
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        {withDates && (
          <>
            <label className="flex items-center gap-1.5">
              From
              <input
                type="date"
                value={from}
                onChange={(event) => {
                  setFrom(event.target.value);
                  void run(query, mode, event.target.value, to);
                }}
                className={input}
              />
            </label>
            <label className="flex items-center gap-1.5">
              To
              <input
                type="date"
                value={to}
                onChange={(event) => {
                  setTo(event.target.value);
                  void run(query, mode, from, event.target.value);
                }}
                className={input}
              />
            </label>
          </>
        )}
        {coverage && (
          <span className="tabular-nums">
            Searchable so far: {coverage.frames} of {coverage.total} frames by scene, {coverage.clips} by action
          </span>
        )}
      </div>

      {running && <p className="text-sm text-zinc-500 dark:text-zinc-400">Searching…</p>}

      {!running && error &&
        (error instanceof ApiError && error.message === ENCODER_UNAVAILABLE ? (
          <Notice title="The search model is unavailable">
            ai_workers is not answering. It may still be loading its model; try again in a minute.
          </Notice>
        ) : (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
            {error instanceof ApiError ? error.message : "could not run this search"}
          </p>
        ))}

      {!running && response && (
        <>
          <p className="text-sm tabular-nums text-zinc-500 dark:text-zinc-400">
            {response.total} result{response.total === 1 ? "" : "s"} in {(response.elapsed_ms / 1000).toFixed(2)} s
          </p>
          {response.results.length > 0 ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
              {response.results.map((hit) => (
                <HitCard key={hit.segment_id} hit={hit} onPick={onPick} />
              ))}
            </div>
          ) : response.message || !hasVectors(mode, coverage) ? (
            <Notice title="Nothing is indexed for this search yet">
              This footage has no {mode === "clip" ? "action" : "scene or action"} vectors so far.
              {mode === "clip" && " Try Scene or Combined."}
            </Notice>
          ) : (
            <Notice title="No results">
              {from || to ? "Nothing matches these dates. Widen or clear them." : "Nothing here matched this search."}
            </Notice>
          )}
        </>
      )}
    </section>
  );
}
