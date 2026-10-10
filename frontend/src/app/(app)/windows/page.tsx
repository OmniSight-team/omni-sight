"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { ApiError, type EventWindow, listSampleWindows } from "@/lib/api-client";
import { DATASET_LABELS, SOURCE_LABELS } from "@/lib/windows";

// The hand-check sample (OMNI-609, D-26/D-27): one lead-up window per sampled clip,
// with the verdict given so far. Each row opens the window's check screen.

function Verdict({ window }: { window: EventWindow }) {
  if (window.verified === null) {
    return <span className="text-xs text-zinc-400 dark:text-zinc-500">Not checked</span>;
  }
  return window.verified ? (
    <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400">
      Correct
    </span>
  ) : (
    <span
      title={window.verify_reason ?? ""}
      className="rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-red-700 dark:bg-red-950/40 dark:text-red-400"
    >
      Wrong
    </span>
  );
}

function Tally({ windows }: { windows: EventWindow[] }) {
  const groups = useMemo(() => {
    const keys = ["ucf_crime_temporal", "uca", "ccd_binlabels"] as const;
    return keys.map((source) => {
      const inGroup = windows.filter((w) => w.annotation_source === source);
      const checked = inGroup.filter((w) => w.verified !== null);
      return {
        source,
        total: inGroup.length,
        checked: checked.length,
        correct: checked.filter((w) => w.verified).length,
      };
    });
  }, [windows]);
  const checked = windows.filter((w) => w.verified !== null).length;

  return (
    <div className="flex flex-wrap gap-3">
      <div className="rounded-xl border border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <p className="text-xs text-zinc-500 dark:text-zinc-400">Checked</p>
        <p className="text-lg font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
          {checked} / {windows.length}
        </p>
      </div>
      {groups.map((g) => (
        <div key={g.source} className="rounded-xl border border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <p className="text-xs text-zinc-500 dark:text-zinc-400">{SOURCE_LABELS[g.source]}</p>
          <p className="text-lg font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
            {g.correct} correct of {g.checked}
            <span className="ml-1 text-xs font-normal text-zinc-400"> ({g.total} in sample)</span>
          </p>
        </div>
      ))}
    </div>
  );
}

export default function SampleWindowsPage() {
  const [windows, setWindows] = useState<EventWindow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listSampleWindows()
      .then(setWindows)
      .catch((err) => setError(err instanceof ApiError ? err.message : "could not load the windows"));
  }, []);

  const firstUnchecked = windows?.find((w) => w.verified === null);

  return (
    <main className="space-y-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Lead-up windows: hand check</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Correct when the window ends where the event visibly begins (within 1.5 s) and shows none of the event.
          </p>
        </div>
        {firstUnchecked && (
          <Link
            href={`/windows/${firstUnchecked.id}`}
            className="rounded-lg bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900"
          >
            Check next →
          </Link>
        )}
      </div>

      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">{error}</p>
      )}
      {windows === null ? (
        !error && <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
      ) : (
        <>
          <Tally windows={windows} />
          <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
            <table className="w-full text-sm">
              <thead className="bg-zinc-50 text-left text-xs text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
                <tr>
                  <th className="px-3 py-2 font-medium">Clip</th>
                  <th className="px-3 py-2 font-medium">Dataset</th>
                  <th className="px-3 py-2 font-medium">Class</th>
                  <th className="px-3 py-2 font-medium">Event time from</th>
                  <th className="px-3 py-2 font-medium">Window</th>
                  <th className="px-3 py-2 font-medium">Verdict</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {windows.map((w) => (
                  <tr key={w.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-900">
                    <td className="px-3 py-2">
                      <Link href={`/windows/${w.id}`} className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
                        {w.clip_key}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-zinc-600 dark:text-zinc-300">{DATASET_LABELS[w.dataset]}</td>
                    <td className="px-3 py-2 text-zinc-600 dark:text-zinc-300">{w.event_class}</td>
                    <td className="px-3 py-2 text-zinc-600 dark:text-zinc-300">{SOURCE_LABELS[w.annotation_source]}</td>
                    <td className="px-3 py-2 tabular-nums text-zinc-600 dark:text-zinc-300">
                      {w.window_start_s.toFixed(1)}–{w.window_end_s.toFixed(1)} s
                      {w.shortened && <span className="ml-1 text-xs text-amber-600">shortened</span>}
                    </td>
                    <td className="px-3 py-2">
                      <Verdict window={w} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </main>
  );
}
