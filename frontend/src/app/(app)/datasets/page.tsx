"use client";

import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { ApiError, type Dataset, listDatasets, loadDataset } from "@/lib/api-client";
import { DATASET_LABELS } from "@/lib/windows";

// The datasets in the product (OMNI-612): clips loaded out of the hand-check sample (D-26:
// the full datasets stay on Drive for Colab), the lead-up windows derived over the whole
// dataset and how many the hand check verified. Admins load clips from here through the
// normal upload path (OMNI-608); while a load runs the screen polls for progress.

const POLL_MS = 2_000;

const STATUS_LABELS: Record<Dataset["status"], string> = {
  not_loaded: "Not loaded",
  loading: "Loading",
  partial: "Partly loaded",
  loaded: "Loaded",
};

const STATUS_STYLES: Record<Dataset["status"], string> = {
  not_loaded: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
  loading: "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-400",
  partial: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
  loaded: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
};

const number = new Intl.NumberFormat();

// GET /datasets may list a dataset the window screens have no label for yet.
function datasetLabel(name: string): string {
  return (DATASET_LABELS as Record<string, string>)[name] ?? name;
}

function LoadControl({ dataset, busy, onQueued }: { dataset: Dataset; busy: boolean; onQueued: () => void }) {
  const [limit, setLimit] = useState(10);
  const [message, setMessage] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSending(true);
    setMessage(null);
    try {
      const { queued } = await loadDataset(dataset.name, limit);
      setMessage(queued === 0 ? "Nothing left to load" : null);
      onQueued();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "could not start the load");
    } finally {
      setSending(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
      <label className="text-sm text-zinc-600 dark:text-zinc-300" htmlFor={`limit-${dataset.name}`}>
        Load up to
      </label>
      <input
        id={`limit-${dataset.name}`}
        type="number"
        min={1}
        value={limit}
        onChange={(e) => setLimit(Math.max(1, Number(e.target.value) || 1))}
        className="w-20 rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm tabular-nums dark:border-zinc-700 dark:bg-zinc-950"
      />
      <span className="text-sm text-zinc-600 dark:text-zinc-300">clips</span>
      <button
        type="submit"
        disabled={busy || sending}
        className="rounded-lg bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
      >
        Load
      </button>
      {busy && <span className="text-xs text-zinc-500 dark:text-zinc-400">A load is running</span>}
      {message && <span className="text-xs text-zinc-500 dark:text-zinc-400">{message}</span>}
    </form>
  );
}

function Progress({ dataset }: { dataset: Dataset }) {
  if (dataset.load_queued === null || dataset.load_done === null) return null;
  const pct = dataset.load_queued === 0 ? 0 : (dataset.load_done / dataset.load_queued) * 100;
  return (
    <div className="space-y-1">
      <div
        className="h-2 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={dataset.load_queued}
        aria-valuenow={dataset.load_done}
        aria-label={`${datasetLabel(dataset.name)} load progress`}
      >
        <div className="h-full bg-indigo-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
        {dataset.load_done} of {dataset.load_queued} queued clips done
      </p>
    </div>
  );
}

function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
      <p className="text-lg font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">{value}</p>
      {detail && <p className="text-xs text-zinc-400 dark:text-zinc-500">{detail}</p>}
    </div>
  );
}

function DatasetCard({
  dataset,
  isAdmin,
  anyLoading,
  onQueued,
}: {
  dataset: Dataset;
  isAdmin: boolean;
  anyLoading: boolean;
  onQueued: () => void;
}) {
  return (
    <section className="space-y-4 rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
            {datasetLabel(dataset.name)}
          </h2>
          <p className="text-sm capitalize text-zinc-500 dark:text-zinc-400">{dataset.domain}</p>
        </div>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_STYLES[dataset.status]}`}>
          {STATUS_LABELS[dataset.status]}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat
          label="Videos loaded"
          value={`${number.format(dataset.videos_loaded)} / ${number.format(dataset.total)}`}
          detail={dataset.failed > 0 ? `${dataset.failed} failed` : "of the hand-check sample"}
        />
        <Stat label="Windows derived" value={number.format(dataset.windows_derived)} detail="whole dataset" />
        <Stat label="Hand-checked" value={number.format(dataset.windows_checked)} />
        <Stat
          label="Verified correct"
          value={number.format(dataset.windows_verified)}
          detail={dataset.windows_checked > 0 ? `of ${dataset.windows_checked} checked` : undefined}
        />
      </div>

      <Progress dataset={dataset} />

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 pt-4 dark:border-zinc-800">
        {isAdmin ? (
          <LoadControl dataset={dataset} busy={anyLoading} onQueued={onQueued} />
        ) : (
          <span />
        )}
        <Link
          href={`/windows?dataset=${dataset.name}`}
          className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
        >
          Windows →
        </Link>
      </div>
    </section>
  );
}

export default function DatasetsPage() {
  const { user } = useAuth();
  const [datasets, setDatasets] = useState<Dataset[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    listDatasets()
      .then((d) => {
        setDatasets(d);
        setError(null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "could not load the datasets"));
  }, []);

  useEffect(refresh, [refresh]);

  const anyLoading = datasets?.some((d) => d.status === "loading") ?? false;

  // Poll only while a load runs; one last fetch when it ends shows the final counts.
  useEffect(() => {
    if (!anyLoading) return;
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [anyLoading, refresh]);

  return (
    <main className="space-y-4 p-6">
      <div>
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Datasets</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          The product holds the hand-check sample; the full datasets stay on Drive for the model runs on Colab.
        </p>
      </div>

      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">{error}</p>
      )}
      {datasets === null ? (
        !error && <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {datasets.map((d) => (
            <DatasetCard
              key={d.name}
              dataset={d}
              isAdmin={user?.role === "admin"}
              anyLoading={anyLoading}
              onQueued={refresh}
            />
          ))}
        </div>
      )}
    </main>
  );
}
