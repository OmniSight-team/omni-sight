import type { EventWindow } from "@/lib/api-client";

// Shared by the hand-check list and the per-window check screen (OMNI-609).

export const SOURCE_LABELS: Record<EventWindow["annotation_source"], string> = {
  ucf_crime_temporal: "Official",
  uca: "UCA",
  ccd_binlabels: "CCD labels",
};

export const DATASET_LABELS: Record<EventWindow["dataset"], string> = {
  ucf_crime: "UCF-Crime",
  ccd: "CCD",
};

// D-27: the reasons a window can be wrong.
export const WRONG_REASONS = ["ends too late", "ends too early", "wrong event", "cannot tell"] as const;

// mm:ss.t: a 1.5 s tolerance needs tenths on screen.
export function formatSeconds(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(1).padStart(4, "0");
  return `${mins}:${secs}`;
}
