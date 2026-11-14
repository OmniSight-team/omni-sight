"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import {
  ApiError,
  type Camera,
  type MatchedBy,
  type SearchBox,
  type SearchBoxes,
  type SearchHit,
  type SearchMode,
  type SearchResponse,
  type SearchScope,
  type SearchSource,
  getEmbeddingStatus,
  getSearchBoxes,
  listCameras,
  searchMoments,
} from "@/lib/api-client";
import { BoxOverlay } from "@/components/box-overlay";
import { SEARCH_INPUT_ID, isTyping } from "@/components/keyboard-shortcuts";

// Natural-language search inside one video or one camera's frames (OMNI-712, FR-4, D-39),
// or over all footage on the Search page (D-43). Every filter runs inside the vector search.

const MODES: { value: SearchMode; label: string }[] = [
  { value: "frame", label: "Scene" },
  { value: "clip", label: "Action" },
  { value: "fused", label: "Combined" },
];

const SOURCES: { value: SearchSource; label: string }[] = [
  { value: "camera", label: "Cameras" },
  { value: "upload", label: "Uploads" },
  { value: "dataset", label: "Datasets" },
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

const number = new Intl.NumberFormat();

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

// Where a hit comes from (D-43): the camera, or the video and, for a dataset clip, its dataset.
function SourceLine({ hit }: { hit: SearchHit }) {
  if (hit.camera && hit.video_id === null) {
    return (
      <p className="truncate text-zinc-700 dark:text-zinc-300" title={hit.camera.name}>
        Camera · {hit.camera.name}
      </p>
    );
  }
  return (
    <p className="flex items-center gap-1.5 text-zinc-700 dark:text-zinc-300">
      {hit.dataset && (
        <span className="shrink-0 rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
          {hit.dataset}
        </span>
      )}
      <span className="truncate" title={hit.filename ?? undefined}>
        {hit.filename ?? `Video ${hit.video_id}`}
      </span>
    </p>
  );
}

function HitCard({
  hit,
  rank,
  boxes,
  showSource = false,
  onPick,
}: {
  hit: SearchHit;
  rank?: number;
  boxes?: SearchBox[];
  showSource?: boolean;
  onPick: (hit: SearchHit, boxes: SearchBox[]) => void;
}) {
  const [size, setSize] = useState({ width: 0, height: 0 });
  return (
    <button
      type="button"
      onClick={() => onPick(hit, boxes ?? [])}
      className="block overflow-hidden rounded-lg border border-zinc-200 text-left transition hover:ring-2 hover:ring-indigo-500 dark:border-zinc-800"
    >
      <div className="relative aspect-video w-full bg-zinc-100 dark:bg-zinc-800">
        {hit.thumb_url && (
          // Thumbnails are served directly by nginx (OMNI-307), not through Next's image optimizer.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={hit.thumb_url}
            alt="Matching frame"
            className="h-full w-full object-cover"
            onLoad={(event) =>
              setSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })
            }
          />
        )}
        <BoxOverlay boxes={boxes} width={size.width} height={size.height} fit="cover" labelSize={0.09} withScore={false} />
      </div>
      <div className="space-y-1 px-2 py-2 text-xs text-zinc-500 dark:text-zinc-400">
        {showSource && <SourceLine hit={hit} />}
        <p className="font-medium tabular-nums text-zinc-900 dark:text-zinc-50">
          {rank !== undefined && <span className="mr-1.5 text-indigo-600 dark:text-indigo-400">#{rank}</span>}
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

// ---- The Search page's look ("Night shift", frontend redesign) -------------------------------
// Only `variant="page"` uses what follows; the player's and the live viewer's search panels keep
// their look until their own screens are redesigned.

// "Both" reads plainer than "Combined" for an operator; the request is the same `fused` mode.
const PAGE_MODE_LABELS: Record<SearchMode, string> = { frame: "Scene", clip: "Action", fused: "Both" };

const PAGE_MATCHED_BY: Record<MatchedBy, string> = {
  frame: "Scene",
  clip: "Action",
  both: "Scene and action",
};

const DATASET_NAMES: Record<string, string> = { virat: "VIRAT", ccd: "CCD", ucf_crime: "UCF-Crime" };

// Fixed examples under the box, to show what kind of sentence works; not suggestions from the system.
const EXAMPLES = ["a car parking", "two people talking", "someone running"];

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-ns-line-strong px-1.5 font-[inherit] text-[11px] text-ns-soft">{children}</kbd>
  );
}

// D-44: one video or camera, the same key the API groups by.
function footageKey(hit: SearchHit): string {
  return hit.video_id !== null ? `video:${hit.video_id}` : `camera:${hit.camera?.id ?? "none"}`;
}

function footageName(hit: SearchHit): string {
  if (hit.video_id === null) return hit.camera?.name ?? "Camera";
  return hit.filename ?? `Video ${hit.video_id}`;
}

function footageKind(hit: SearchHit): string {
  if (hit.video_id === null) return "Camera, stored frames";
  if (hit.dataset) return `${DATASET_NAMES[hit.dataset] ?? hit.dataset} dataset clip`;
  if (hit.camera) return `Recording from ${hit.camera.name}`;
  return "Upload";
}

function momentTime(hit: SearchHit): string {
  return hit.video_id === null ? new Date(hit.captured_at).toLocaleString() : formatPosition(hit.timestamp_s);
}

type FootageGroup = { key: string; hits: SearchHit[] };

// In rank order: a group sits where its best moment ranked.
function groupByFootage(hits: SearchHit[]): FootageGroup[] {
  const groups = new Map<string, SearchHit[]>();
  for (const hit of hits) {
    const key = footageKey(hit);
    groups.set(key, [...(groups.get(key) ?? []), hit]);
  }
  return [...groups].map(([key, groupHits]) => ({ key, hits: groupHits }));
}

// One moment: its frame, its time, and how strongly it matched next to the best result of this
// search (the bar). The raw score shows on hover or keyboard focus.
function MomentTile({
  hit,
  top,
  boxes,
  withSource = false,
  onPick,
}: {
  hit: SearchHit;
  top: number;
  boxes?: SearchBox[];
  withSource?: boolean;
  onPick: (hit: SearchHit, boxes: SearchBox[]) => void;
}) {
  const [size, setSize] = useState({ width: 0, height: 0 });
  const strength = top > 0 ? Math.max(4, Math.round((hit.score / top) * 100)) : 0;
  const score = hit.score.toFixed(4);
  const common = {
    "data-moment": true,
    title: `Score ${score}`,
    "aria-label": `${footageName(hit)} at ${momentTime(hit)}, ${PAGE_MATCHED_BY[hit.matched_by]}, score ${score}`,
    className:
      "group block w-full min-w-0 rounded-md text-left text-ns-text no-underline outline-none focus-visible:ring-2 focus-visible:ring-ns-accent",
  };
  const body = (
    <>
      <div className="relative aspect-video w-full overflow-hidden rounded-md bg-ns-raised ring-ns-accent transition group-hover:ring-2">
        {hit.thumb_url && (
          // Thumbnails are served directly by nginx (OMNI-307), not through Next's image optimizer.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={hit.thumb_url}
            alt=""
            width={320}
            height={180}
            loading="lazy"
            className="h-full w-full object-cover"
            onLoad={(event) =>
              setSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })
            }
          />
        )}
        <BoxOverlay boxes={boxes} width={size.width} height={size.height} fit="cover" labelSize={0.09} withScore={false} />
        <span className="absolute bottom-2 left-2 rounded bg-[#0c0f13]/85 px-2 py-0.5 text-[13px] font-medium text-ns-text">
          {momentTime(hit)}
        </span>
      </div>
      {withSource && <p className="mt-2 truncate text-sm font-medium text-ns-text">{footageName(hit)}</p>}
      <div className="mt-2 flex items-center gap-2.5">
        <span className="h-1 min-w-8 flex-1 overflow-hidden rounded-sm bg-ns-line" aria-hidden="true">
          <span className="block h-full bg-ns-accent" style={{ width: `${strength}%` }} />
        </span>
        <span className="shrink-0 text-[13px] text-ns-muted">
          {PAGE_MATCHED_BY[hit.matched_by]}
          <span className="hidden text-ns-soft group-hover:inline group-focus-visible:inline">, {score}</span>
        </span>
      </div>
    </>
  );

  // A video moment is a real link to the player at that second, so Ctrl/Cmd-click and a middle
  // click open it in a new tab; a plain click goes through `onPick`, which also hands over the
  // result's boxes. A camera moment has no page of its own: it is a button.
  if (hit.video_id !== null) {
    return (
      <a
        {...common}
        href={`/videos/${hit.video_id}?t=${hit.timestamp_s}`}
        onClick={(event) => {
          if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          event.preventDefault();
          onPick(hit, boxes ?? []);
        }}
      >
        {body}
      </a>
    );
  }
  return (
    <button type="button" {...common} onClick={() => onPick(hit, boxes ?? [])}>
      {body}
    </button>
  );
}

function PageNotice({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-ns-line bg-ns-panel px-5 py-8 text-center">
      <p className="font-medium text-ns-text">{title}</p>
      <p className="mt-1 text-sm text-ns-muted">{children}</p>
    </div>
  );
}

// Buttons joined into one control: the mode, the sources. Every filter on the page is this
// shape, a select or a date field, all the same height.
function Segmented({
  label,
  options,
  isOn,
  onToggle,
}: {
  label: string;
  options: { value: string; label: string }[];
  isOn: (value: string) => boolean;
  onToggle: (value: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-ns-muted">{label}</span>
      <div role="group" aria-label={label} className="inline-flex overflow-hidden rounded-md border border-ns-line-strong">
        {options.map((option, index) => {
          const on = isOn(option.value);
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={on}
              onClick={() => onToggle(option.value)}
              className={`h-9 px-3.5 outline-none transition focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ns-accent ${
                index > 0 ? "border-l border-ns-line-strong" : ""
              } ${on ? "bg-ns-selected font-medium text-ns-text" : "text-ns-soft hover:bg-ns-raised hover:text-ns-text"}`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function hasVectors(mode: SearchMode, coverage: Coverage | null): boolean {
  if (coverage === null) return true;
  if (mode === "frame") return coverage.frames > 0;
  if (mode === "clip") return coverage.clips > 0;
  return coverage.frames > 0 || coverage.clips > 0;
}

type Filters = {
  mode: SearchMode;
  from: string;
  to: string;
  compare: boolean;
  sources: SearchSource[];
  cameraId: number | null;
};

const MODE_VALUES = new Set<string>(MODES.map((option) => option.value));
const SOURCE_VALUES = new Set<string>(SOURCES.map((option) => option.value));

// K-33: the Search page keeps its search in its own URL, so going back from a result opens
// the same search again (a repeated query's text vector is cached, so it is quick).
function searchToUrl(text: string, filters: Filters): string {
  const query = new URLSearchParams({ q: text, mode: filters.mode });
  if (filters.compare) query.set("compare", "1");
  for (const source of filters.sources) query.append("source", source);
  if (filters.cameraId !== null) query.set("camera", String(filters.cameraId));
  if (filters.from) query.set("from", filters.from);
  if (filters.to) query.set("to", filters.to);
  return `?${query}`;
}

function searchFromUrl(search: string): { text: string; filters: Filters } | null {
  const query = new URLSearchParams(search);
  const text = query.get("q")?.trim() ?? "";
  if (!text) return null;
  const mode = query.get("mode") ?? "";
  const camera = Number(query.get("camera"));
  return {
    text,
    filters: {
      mode: MODE_VALUES.has(mode) ? (mode as SearchMode) : "fused",
      compare: query.get("compare") === "1",
      sources: query.getAll("source").filter((value) => SOURCE_VALUES.has(value)) as SearchSource[],
      cameraId: query.get("camera") && Number.isInteger(camera) ? camera : null,
      from: query.get("from") ?? "",
      to: query.get("to") ?? "",
    },
  };
}

export function MomentSearch({
  scope,
  withDates = false,
  withFilters = false,
  showSource = false,
  k,
  perFootage,
  inUrl = false,
  savedUrl,
  variant = "panel",
  onPick,
}: {
  scope: SearchScope;
  // "page": the Search page's own look (frontend redesign); "panel": the player and live viewer.
  variant?: "panel" | "page";
  withDates?: boolean;
  // The Search page (D-43): source and camera filters.
  withFilters?: boolean;
  // Where each hit comes from (D-43).
  showSource?: boolean;
  // Results per mode; the API's default (5) when not given.
  k?: number;
  // D-44: at most this many moments of one video or camera.
  perFootage?: number;
  // K-33: keep the search in the page's URL; `savedUrl` is that URL's query on opening, whose
  // search runs again (on coming back from a result too).
  inUrl?: boolean;
  savedUrl?: string;
  // With the result's boxes (OMNI-X02), empty when it has none or they have not arrived yet,
  // and the query that found it.
  onPick: (hit: SearchHit, boxes: SearchBox[], query: string) => void;
}) {
  // Read once, on opening: later URL changes are this panel's own.
  const [saved] = useState(() => (inUrl && savedUrl ? searchFromUrl(savedUrl) : null));
  const [draft, setDraft] = useState(saved?.text ?? "");
  const [boxes, setBoxes] = useState<SearchBoxes>({});
  const [mode, setMode] = useState<SearchMode>(saved?.filters.mode ?? "fused");
  const [from, setFrom] = useState(saved?.filters.from ?? "");
  const [to, setTo] = useState(saved?.filters.to ?? "");
  const [query, setQuery] = useState("");
  const [running, setRunning] = useState(false);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  // Comparison (OMNI-716): the same query answered in all three modes, side by side.
  const [compare, setCompare] = useState(saved?.filters.compare ?? false);
  const [columns, setColumns] = useState<Record<SearchMode, SearchResponse> | null>(null);
  // D-43: none ticked means every source.
  const [sources, setSources] = useState<SearchSource[]>(saved?.filters.sources ?? []);
  const [cameraId, setCameraId] = useState<number | null>(saved?.filters.cameraId ?? null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  // Only the newest search may show its answer: an older, slower one is ignored.
  const latest = useRef(0);
  const scopeKey = JSON.stringify(scope);
  const pickHit = (hit: SearchHit, found: SearchBox[]) => onPick(hit, found, query);
  // The Search page's results, for J and K (frontend redesign).
  const resultsRef = useRef<HTMLDivElement>(null);

  // J and K move the keyboard focus through the results in rank order; Enter opens the focused one
  // (each result is a button). Only on the Search page, and never while typing.
  useEffect(() => {
    if (variant !== "page") return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || isTyping(event.target)) return;
      const key = event.key.toLowerCase();
      if (key !== "j" && key !== "k") return;
      const moments = [...(resultsRef.current?.querySelectorAll<HTMLElement>("[data-moment]") ?? [])];
      if (moments.length === 0) return;
      event.preventDefault();
      const at = moments.indexOf(document.activeElement as HTMLElement);
      const next =
        at === -1 ? (key === "j" ? 0 : moments.length - 1) : Math.min(moments.length - 1, Math.max(0, at + (key === "j" ? 1 : -1)));
      moments[next].focus();
      moments[next].scrollIntoView({ block: "nearest" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [variant]);

  useEffect(() => {
    if (!withFilters) return;
    listCameras()
      .then(setCameras)
      .catch(() => {
        // Non-fatal: the search works without the camera filter.
      });
  }, [withFilters]);

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

  // Each call names what the click changed; the rest is the current state (the click's own
  // setState is not visible here yet).
  async function run(text: string, changed: Partial<Filters> = {}) {
    const next: Filters = { mode, from, to, compare, sources, cameraId, ...changed };
    if (!text) return;
    if (inUrl) window.history.replaceState(null, "", searchToUrl(text, next));
    const params = {
      q: text,
      k,
      per_footage: perFootage,
      ...(JSON.parse(scopeKey) as SearchScope),
      ...(next.cameraId !== null ? { camera_id: next.cameraId } : {}),
      source: next.sources.length > 0 ? next.sources : undefined,
      from: next.from ? dayStart(next.from) : undefined,
      to: next.to ? dayEnd(next.to) : undefined,
    };
    const ticket = ++latest.current;
    setQuery(text);
    setRunning(true);
    setBoxes({});
    // OMNI-X02: the boxes are a second request, sent once the results are on the screen.
    const askForBoxes = (results: SearchHit[]) => {
      const ids = [...new Set(results.map((hit) => hit.segment_id))];
      void getSearchBoxes(text, ids).then((found) => {
        if (ticket === latest.current) setBoxes(found);
      });
    };
    try {
      if (next.compare) {
        const [frame, clip, fused] = await Promise.all(
          MODES.map((option) => searchMoments({ ...params, mode: option.value })),
        );
        if (ticket !== latest.current) return;
        setColumns({ frame, clip, fused });
        setError(null);
        askForBoxes([...frame.results, ...clip.results, ...fused.results]);
        return;
      }
      const answer = await searchMoments({ ...params, mode: next.mode });
      if (ticket !== latest.current) return;
      setResponse(answer);
      setError(null);
      askForBoxes(answer.results);
    } catch (err) {
      if (ticket !== latest.current) return;
      setResponse(null);
      setError(err instanceof Error ? err : new Error("could not run this search"));
    } finally {
      if (ticket === latest.current) setRunning(false);
    }
  }

  // K-33: on opening (also on coming back from a result), the search in the URL runs again.
  useEffect(() => {
    if (saved === null) return;
    // Started after this render, not inside it; a second mount (development) cancels the first.
    const timer = setTimeout(() => void run(saved.text, saved.filters), 0);
    return () => clearTimeout(timer);
    // Once, on opening: `run` is given every filter, so it needs nothing from this render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved]);

  function submit(event: FormEvent) {
    event.preventDefault();
    void run(draft.trim());
  }

  if (variant === "page") {
    const control =
      "h-9 rounded-md border border-ns-line-strong bg-ns-ground px-2.5 text-ns-text outline-none [color-scheme:dark] focus-visible:ring-2 focus-visible:ring-ns-accent";
    const filtered = Boolean(from || to || sources.length > 0 || cameraId !== null);
    const groups = response ? groupByFootage(response.results) : [];
    const bestOf = (hits: SearchHit[]) => hits.reduce((best, hit) => Math.max(best, hit.score), 0);
    const top = response ? bestOf(response.results) : 0;
    const partial = coverage !== null && coverage.total > 0 && coverage.frames < coverage.total;

    return (
      <section className="space-y-5">
        <form onSubmit={submit} className="space-y-3.5 rounded-lg border border-ns-line bg-ns-panel p-5">
          <div className="flex flex-wrap gap-2.5">
            <div className="relative min-w-0 flex-[1_1_360px]">
              <label htmlFor={SEARCH_INPUT_ID} className="sr-only">
                Describe what happened
              </label>
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden="true"
                className="pointer-events-none absolute top-[17px] left-4 text-ns-muted"
              >
                <circle cx="11" cy="11" r="7" />
                <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
              </svg>
              <input
                id={SEARCH_INPUT_ID}
                name="q"
                type="search"
                autoComplete="off"
                // The one thing to do on this page: the cursor is in the box on arrival, unless a
                // search from the URL is already showing its results.
                autoFocus={saved === null}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  // Esc leaves the box (so J and K work) without clearing what was typed, which a
                  // search field does by default.
                  if (event.key === "Escape") {
                    event.preventDefault();
                    event.currentTarget.blur();
                  }
                }}
                placeholder="a person opening the trunk of a car…"
                maxLength={1000}
                className="h-[52px] w-full rounded-md border border-ns-line-strong bg-ns-ground pr-4 pl-11 text-lg text-ns-text outline-none placeholder:text-ns-muted focus-visible:border-ns-accent focus-visible:ring-3 focus-visible:ring-ns-accent/25"
              />
            </div>
            <button
              type="submit"
              disabled={!draft.trim()}
              className="h-[52px] rounded-md bg-ns-accent px-7 font-semibold text-ns-accent-ink outline-none transition hover:bg-ns-accent-hover focus-visible:ring-2 focus-visible:ring-ns-text disabled:opacity-50"
            >
              Search
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-[13px] text-ns-muted">
            <span>Try</span>
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => {
                  setDraft(example);
                  void run(example);
                }}
                className="h-7 rounded-full border border-ns-line-strong px-2.5 text-ns-soft transition hover:border-ns-accent hover:text-ns-text focus-visible:ring-2 focus-visible:ring-ns-accent focus-visible:outline-none"
              >
                {example}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-x-5 gap-y-3 text-sm">
            {!compare && (
              <Segmented
                label="Match by"
                options={MODES.map((option) => ({ value: option.value, label: PAGE_MODE_LABELS[option.value] }))}
                isOn={(value) => mode === value}
                onToggle={(value) => {
                  setMode(value as SearchMode);
                  void run(query, { mode: value as SearchMode });
                }}
              />
            )}
            {withFilters && (
              <Segmented
                label="Footage"
                options={SOURCES}
                isOn={(value) => sources.includes(value as SearchSource)}
                onToggle={(value) => {
                  const source = value as SearchSource;
                  const nextSources = sources.includes(source)
                    ? sources.filter((s) => s !== source)
                    : [...sources, source];
                  setSources(nextSources);
                  void run(query, { sources: nextSources });
                }}
              />
            )}
            {withFilters && (
              <label className="flex items-center gap-2 text-ns-muted">
                Camera
                <select
                  value={cameraId ?? ""}
                  onChange={(event) => {
                    const nextCamera = event.target.value ? Number(event.target.value) : null;
                    setCameraId(nextCamera);
                    void run(query, { cameraId: nextCamera });
                  }}
                  className={control}
                >
                  <option value="">Any camera</option>
                  {cameras.map((camera) => (
                    <option key={camera.id} value={camera.id}>
                      {camera.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {withDates && (
              <>
                <label className="flex items-center gap-2 text-ns-muted">
                  From
                  <input
                    type="date"
                    value={from}
                    onChange={(event) => {
                      setFrom(event.target.value);
                      void run(query, { from: event.target.value });
                    }}
                    className={control}
                  />
                </label>
                <label className="flex items-center gap-2 text-ns-muted">
                  To
                  <input
                    type="date"
                    value={to}
                    onChange={(event) => {
                      setTo(event.target.value);
                      void run(query, { to: event.target.value });
                    }}
                    className={control}
                  />
                </label>
              </>
            )}
            <button
              type="button"
              aria-pressed={compare}
              onClick={() => {
                const next = !compare;
                setCompare(next);
                void run(query, { compare: next });
              }}
              className={`h-9 rounded-md border px-3.5 outline-none transition focus-visible:ring-2 focus-visible:ring-ns-accent lg:ml-auto ${
                compare
                  ? "border-ns-accent bg-ns-selected font-medium text-ns-text"
                  : "border-ns-line-strong text-ns-soft hover:bg-ns-raised hover:text-ns-text"
              }`}
            >
              {compare ? "Back to one list" : "Compare scene and action"}
            </button>
          </div>
        </form>

        {partial && (
          <p className="text-sm text-ns-muted">
            Not every frame is searchable yet: {number.format(coverage.frames)} of {number.format(coverage.total)} by
            scene, {number.format(coverage.clips)} by action.
          </p>
        )}

        {running && (
          <div role="status" className="space-y-2.5">
            <p className="text-ns-muted">Searching every video, dataset clip and camera…</p>
            <div aria-hidden="true" className="h-0.5 overflow-hidden rounded-full bg-ns-line">
              <div className="h-full w-2/5 bg-ns-accent motion-safe:animate-ns-scan" />
            </div>
          </div>
        )}

        {!running && error &&
          (error instanceof ApiError && error.message === ENCODER_UNAVAILABLE ? (
            <PageNotice title="The search model is not answering">
              It may still be starting. Try again in a minute.
            </PageNotice>
          ) : (
            <p className="rounded-md border border-ns-fault/40 bg-ns-fault/10 px-4 py-3 text-sm text-ns-text">
              {error instanceof ApiError ? error.message : "Could not run this search."}
            </p>
          ))}

        <div ref={resultsRef} className="space-y-4">
        {!running && compare && columns && (
          <div className="grid gap-6 md:grid-cols-3">
            {MODES.map((option) => {
              const column = columns[option.value];
              const columnTop = bestOf(column.results);
              return (
                <div key={option.value} className="space-y-3">
                  <h2 className="font-semibold text-ns-text">
                    {PAGE_MODE_LABELS[option.value]}
                    <span className="ml-2 text-sm font-normal text-ns-muted">
                      {column.total} in {(column.elapsed_ms / 1000).toFixed(1)}&nbsp;s
                    </span>
                  </h2>
                  {column.results.length > 0 ? (
                    <ol className="space-y-4">
                      {column.results.map((hit) => (
                        <li key={hit.segment_id}>
                          <MomentTile
                            hit={hit}
                            top={columnTop}
                            boxes={boxes[hit.segment_id]}
                            withSource
                            onPick={pickHit}
                          />
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <PageNotice title="No results">{column.message ?? "Nothing here matched this search."}</PageNotice>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {!running && !compare && response && (
          <>
            {response.results.length > 0 && (
              <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
                <p className="text-base text-ns-text">
                  <span className="font-semibold">
                    {response.total} moment{response.total === 1 ? "" : "s"}
                  </span>{" "}
                  from {groups.length === 1 ? "1 video or camera" : `${groups.length} videos and cameras`}, found in{" "}
                  {(response.elapsed_ms / 1000).toFixed(1)}&nbsp;s
                </p>
                <p className="flex gap-3.5 text-[13px] text-ns-muted">
                  <span>
                    <Kbd>J</Kbd> <Kbd>K</Kbd> next and previous
                  </span>
                  <span>
                    <Kbd>Enter</Kbd> open
                  </span>
                </p>
              </div>
            )}
            {response.results.length > 0 ? (
              <ol className="overflow-hidden rounded-lg border border-ns-line bg-ns-panel">
                {groups.map((group, index) => {
                  const first = group.hits[0];
                  return (
                    <li
                      key={group.key}
                      className={`flex flex-wrap gap-x-6 gap-y-4 px-5 py-4 ${index > 0 ? "border-t border-ns-line" : ""}`}
                    >
                      <div className="flex min-w-[200px] flex-[0_1_260px] gap-3.5">
                        <span className="flex size-7 flex-none items-center justify-center rounded-full bg-ns-raised text-[13px] font-semibold text-ns-soft">
                          {index + 1}
                        </span>
                        <div className="min-w-0">
                          <p className="font-medium break-words text-ns-text">{footageName(first)}</p>
                          <p className="mt-0.5 text-[13px] text-ns-muted">{footageKind(first)}</p>
                        </div>
                      </div>
                      <div className="flex min-w-0 flex-[1_1_480px] flex-wrap gap-3">
                        {group.hits.map((hit) => (
                          <div key={hit.segment_id} className="min-w-[200px] flex-[0_1_280px]">
                            <MomentTile hit={hit} top={top} boxes={boxes[hit.segment_id]} onPick={pickHit} />
                          </div>
                        ))}
                      </div>
                    </li>
                  );
                })}
              </ol>
            ) : response.message || !hasVectors(mode, coverage) ? (
              <PageNotice title="Nothing is indexed for this search yet">
                This footage has no {mode === "clip" ? "action" : "scene or action"} vectors so far.
                {mode === "clip" && " Try Scene or Both."}
              </PageNotice>
            ) : (
              <PageNotice title="No results">
                {filtered
                  ? "Nothing matches these filters. Widen the dates or clear a filter."
                  : mode === "fused"
                    ? "Nothing matched. Try fewer words, or match by Scene instead of Both."
                    : "Nothing matched. Try fewer words, or match by Both."}
              </PageNotice>
            )}
          </>
        )}
        </div>
      </section>
    );
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
        {!compare && (
        <div className="inline-flex rounded-lg border border-zinc-200 p-0.5 dark:border-zinc-800">
          {MODES.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={mode === option.value}
              onClick={() => {
                setMode(option.value);
                void run(query, { mode: option.value });
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
        )}
        <button
          type="button"
          aria-pressed={compare}
          onClick={() => {
            const next = !compare;
            setCompare(next);
            void run(query, { compare: next });
          }}
          className={`rounded-lg border px-3 py-1 font-medium transition ${
            compare
              ? "border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
              : "border-zinc-200 text-zinc-500 hover:text-zinc-900 dark:border-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-100"
          }`}
        >
          Compare
        </button>
        {withDates && (
          <>
            <label className="flex items-center gap-1.5">
              From
              <input
                type="date"
                value={from}
                onChange={(event) => {
                  setFrom(event.target.value);
                  void run(query, { from: event.target.value });
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
                  void run(query, { to: event.target.value });
                }}
                className={input}
              />
            </label>
          </>
        )}
        {withFilters && (
          <>
            <div
              role="group"
              aria-label="Source"
              className="inline-flex rounded-lg border border-zinc-200 p-0.5 dark:border-zinc-800"
            >
              {SOURCES.map((option) => {
                const on = sources.includes(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={on}
                    onClick={() => {
                      const nextSources = on ? sources.filter((s) => s !== option.value) : [...sources, option.value];
                      setSources(nextSources);
                      void run(query, { sources: nextSources });
                    }}
                    className={`rounded-md px-3 py-1 font-medium transition ${
                      on
                        ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                        : "text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
                    }`}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            <label className="flex items-center gap-1.5">
              Camera
              <select
                value={cameraId ?? ""}
                onChange={(event) => {
                  const nextCamera = event.target.value ? Number(event.target.value) : null;
                  setCameraId(nextCamera);
                  void run(query, { cameraId: nextCamera });
                }}
                className={input}
              >
                <option value="">Any</option>
                {cameras.map((camera) => (
                  <option key={camera.id} value={camera.id}>
                    {camera.name}
                  </option>
                ))}
              </select>
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

      {!running && compare && columns && (
        <div className="grid gap-4 md:grid-cols-3">
          {MODES.map((option) => {
            const column = columns[option.value];
            return (
              <div key={option.value} className="space-y-2">
                <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
                  {option.label}
                  <span className="ml-2 font-normal tabular-nums text-zinc-500 dark:text-zinc-400">
                    {column.total} result{column.total === 1 ? "" : "s"} in {(column.elapsed_ms / 1000).toFixed(2)} s
                  </span>
                </p>
                {column.results.length > 0 ? (
                  <div className="grid grid-cols-1 gap-3">
                    {column.results.map((hit, index) => (
                      <HitCard
                        key={hit.segment_id}
                        hit={hit}
                        rank={index + 1}
                        boxes={boxes[hit.segment_id]}
                        showSource={showSource}
                        onPick={pickHit}
                      />
                    ))}
                  </div>
                ) : (
                  <Notice title="No results">
                    {column.message ?? "Nothing here matched this search."}
                  </Notice>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!running && !compare && response && (
        <>
          <p className="text-sm tabular-nums text-zinc-500 dark:text-zinc-400">
            {response.total} result{response.total === 1 ? "" : "s"} in {(response.elapsed_ms / 1000).toFixed(2)} s
          </p>
          {response.results.length > 0 ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
              {response.results.map((hit) => (
                <HitCard
                  key={hit.segment_id}
                  hit={hit}
                  boxes={boxes[hit.segment_id]}
                  showSource={showSource}
                  onPick={pickHit}
                />
              ))}
            </div>
          ) : response.message || !hasVectors(mode, coverage) ? (
            <Notice title="Nothing is indexed for this search yet">
              This footage has no {mode === "clip" ? "action" : "scene or action"} vectors so far.
              {mode === "clip" && " Try Scene or Combined."}
            </Notice>
          ) : (
            <Notice title="No results">
              {from || to || sources.length > 0 || cameraId !== null
                ? "Nothing matches these filters. Widen or clear them."
                : "Nothing here matched this search."}
            </Notice>
          )}
        </>
      )}
    </section>
  );
}
