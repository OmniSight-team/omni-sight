"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { type SearchBox, type SearchHit, fetchFrameImage } from "@/lib/api-client";
import { BoxOverlay } from "@/components/box-overlay";
import { MomentSearch } from "@/components/moment-search";
import { storePick } from "@/lib/search-pick";

// Results per mode. Compare asks the three modes at once and their boxes in one request, which
// takes at most 50 frames (`GET /search/boxes`), so 3 x 16 fits.
const RESULTS_PER_MODE = 16;

// D-44: at most this many moments of one video or camera, so one video's near-identical frames
// do not fill the page and other footage shows.
const PER_FOOTAGE = 2;

// The Search page (D-43, FR-4): one query over every video, dataset clip and camera. A video
// result opens the player at that second, paused, with its boxes; a camera keeps frames, not a
// recording (K-29), so a camera result opens its stored frame here.
export default function SearchPage() {
  // The search is read from the URL (K-33), which is only known in the browser.
  return (
    <Suspense>
      <SearchView />
    </Suspense>
  );
}

function SearchView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [picked, setPicked] = useState<SearchHit | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [boxes, setBoxes] = useState<SearchBox[]>([]);
  const [size, setSize] = useState({ width: 0, height: 0 });

  function pick(hit: SearchHit, found: SearchBox[], query: string) {
    if (hit.video_id !== null) {
      storePick({ videoId: hit.video_id, at: hit.timestamp_s, segmentId: hit.segment_id, q: query, boxes: found });
      router.push(`/videos/${hit.video_id}?t=${hit.timestamp_s}`);
      return;
    }
    if (!hit.frame_url) return;
    setPicked(hit);
    setBoxes(found);
    setSize({ width: 0, height: 0 });
    setSrc(null);
    setError(null);
    fetchFrameImage(hit.frame_url)
      .then((blob) => setSrc(URL.createObjectURL(blob)))
      .catch(() => setError("Could not load this frame."));
  }

  function back() {
    if (src) URL.revokeObjectURL(src);
    setPicked(null);
    setSrc(null);
  }

  // The first screen in the "Night shift" look (frontend redesign): graphite ground, IBM Plex.
  return (
    <main className="min-h-full space-y-5 bg-ns-ground px-8 pt-7 pb-10 font-console text-[15px] leading-normal text-ns-text tabular-nums [color-scheme:dark]">
      <div>
        <h1 className="text-2xl leading-tight font-semibold">Search</h1>
        <p className="mt-1 text-ns-muted">
          Describe what happened. Every video, dataset clip and camera is searched at once.
        </p>
      </div>

      {picked && (
        <div className="space-y-3">
          <div className="relative overflow-hidden rounded-lg border border-ns-line bg-black">
            {src && (
              // An object URL from an authenticated fetch.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={src}
                alt={`Frame at ${picked.captured_at}`}
                className="block aspect-video w-full object-contain"
                onLoad={(event) =>
                  setSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })
                }
              />
            )}
            {src && <BoxOverlay boxes={boxes} width={size.width} height={size.height} fit="contain" />}
            {error && <p className="p-6 text-sm text-ns-fault">{error}</p>}
            <span className="absolute top-3 left-3 rounded bg-[#0c0f13]/85 px-2 py-1 text-[13px] font-medium text-ns-text">
              {picked.camera?.name}, {new Date(picked.captured_at).toLocaleString()}
            </span>
          </div>
          <button
            type="button"
            onClick={back}
            className="h-9 rounded-md border border-ns-line-strong px-3.5 text-sm text-ns-soft outline-none transition hover:bg-ns-raised hover:text-ns-text focus-visible:ring-2 focus-visible:ring-ns-accent"
          >
            Back to results
          </button>
        </div>
      )}

      {/* Kept mounted under an opened frame, so going back does not search again. */}
      <div className={picked ? "hidden" : undefined}>
        <MomentSearch
          scope={{}}
          withDates
          withFilters
          showSource
          k={RESULTS_PER_MODE}
          perFootage={PER_FOOTAGE}
          inUrl
          savedUrl={searchParams.toString()}
          variant="page"
          onPick={pick}
        />
      </div>
    </main>
  );
}
