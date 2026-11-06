import { type SearchBox, getSearchBoxes } from "@/lib/api-client";

// A result picked on the Search page (D-43), handed to the video player it opens. The second
// is in the URL (`?t=`); the boxes are too long for it, so they wait here for that one video
// and second. Read once, then removed. A result clicked before its boxes arrived (about 0.4 s
// a frame on the CPU) carries none: the player then asks for that one frame's boxes itself.

const KEY = "omnisight.search-pick";

export type SearchPick = { videoId: number; at: number; segmentId: number; q: string; boxes: SearchBox[] };

export function storePick(pick: SearchPick): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(pick));
  } catch {
    // Storage blocked: the player still opens at that second, without the boxes.
  }
}

function readPick(videoId: number, at: number): SearchPick | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    if (!raw) return null;
    const pick = JSON.parse(raw) as SearchPick;
    return pick.videoId === videoId && pick.at === at ? pick : null;
  } catch {
    return null;
  }
}

// The picked result's boxes, or none if this video and second were not opened from a pick.
export async function takePickBoxes(videoId: number, at: number): Promise<SearchBox[]> {
  const pick = readPick(videoId, at);
  if (pick === null) return [];
  if (pick.boxes.length > 0) return pick.boxes;
  const found = await getSearchBoxes(pick.q, [pick.segmentId]);
  return found[pick.segmentId] ?? [];
}
