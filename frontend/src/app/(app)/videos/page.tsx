"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ChangeEvent } from "react";

import {
  ApiError,
  type Camera,
  type Video,
  type VideoListFilters,
  type VideoSource,
  type VideoStatus,
  deleteVideo,
  listCameras,
  listVideos,
  uploadVideo,
} from "@/lib/api-client";

const SOURCES: VideoSource[] = ["upload", "camera", "dataset"];

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

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

function formatSize(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb < 1 ? `${Math.round(bytes / 1024)} KB` : `${mb.toFixed(1)} MB`;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function toFromIso(dateOnly: string): string {
  return `${dateOnly}T00:00:00.000Z`;
}

function toToIso(dateOnly: string): string {
  return `${dateOnly}T23:59:59.999Z`;
}

export default function VideosPage() {
  const [videos, setVideos] = useState<Video[] | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [listError, setListError] = useState<string | null>(null);

  const [sourceFilter, setSourceFilter] = useState<VideoSource | "">("");
  const [cameraFilter, setCameraFilter] = useState("");
  const [fromFilter, setFromFilter] = useState("");
  const [toFilter, setToFilter] = useState("");

  const [uploading, setUploading] = useState(false);
  const [uploadFileName, setUploadFileName] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadMessage, setUploadMessage] = useState<{ kind: "success" | "error"; text: string } | null>(
    null,
  );

  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const cameraNames = new Map(cameras.map((camera) => [camera.id, camera.name]));

  function buildFilters(): VideoListFilters {
    const filters: VideoListFilters = {};
    if (sourceFilter) filters.source = sourceFilter;
    if (cameraFilter) filters.camera_id = Number(cameraFilter);
    if (fromFilter) filters.from = toFromIso(fromFilter);
    if (toFilter) filters.to = toToIso(toFilter);
    return filters;
  }

  async function refreshVideos() {
    try {
      setVideos(await listVideos(buildFilters()));
      setListError(null);
    } catch (err) {
      setListError(errorMessage(err, "could not load videos"));
    }
  }

  // Re-runs whenever a filter changes, and on first mount — the filters all
  // start empty, so the first run is an unfiltered load of the archive.
  useEffect(() => {
    listVideos(buildFilters())
      .then((rows) => {
        setVideos(rows);
        setListError(null);
      })
      .catch((err) => {
        setListError(errorMessage(err, "could not load videos"));
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceFilter, cameraFilter, fromFilter, toFilter]);

  useEffect(() => {
    listCameras()
      .then(setCameras)
      .catch(() => {
        // Non-fatal — the table just shows a raw camera id if names can't
        // be resolved.
      });
  }, []);

  function openFilePicker() {
    fileInputRef.current?.click();
  }

  function handleFileSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";
    if (file) void handleUpload(file);
  }

  async function handleUpload(file: File) {
    setUploading(true);
    setUploadFileName(file.name);
    setUploadProgress(0);
    setUploadMessage(null);
    try {
      const result = await uploadVideo(file, setUploadProgress);
      setUploadMessage(
        result.status === "failed"
          ? { kind: "error", text: `${file.name}: ${result.error ?? "processing failed"}` }
          : { kind: "success", text: `${file.name} uploaded — ${result.status}` },
      );
      await refreshVideos();
    } catch (err) {
      setUploadMessage({ kind: "error", text: errorMessage(err, "upload failed") });
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(video: Video) {
    setDeletingId(video.id);
    try {
      await deleteVideo(video.id);
      await refreshVideos();
    } catch (err) {
      setListError(errorMessage(err, "could not delete this video"));
    } finally {
      setDeletingId(null);
      setConfirmDeleteId(null);
    }
  }

  const filtersActive = sourceFilter !== "" || cameraFilter !== "" || fromFilter !== "" || toFilter !== "";

  return (
    <main className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Video Archive</h1>
        <div>
          <input
            ref={fileInputRef}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={handleFileSelected}
          />
          <button
            type="button"
            onClick={openFilePicker}
            disabled={uploading}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {uploading ? "Uploading…" : "Upload Video"}
          </button>
        </div>
      </div>

      {uploading && (
        <div className="mb-4 rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="mb-1.5 flex items-center justify-between text-sm text-zinc-600 dark:text-zinc-400">
            <span className="truncate">{uploadFileName}</span>
            <span>{uploadProgress}%</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
            <div
              className="h-full rounded-full bg-indigo-600 transition-[width]"
              style={{ width: `${uploadProgress}%` }}
            />
          </div>
        </div>
      )}

      {uploadMessage && (
        <p
          className={`mb-4 rounded-lg px-3 py-2 text-sm ${
            uploadMessage.kind === "success"
              ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400"
              : "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400"
          }`}
        >
          {uploadMessage.text}
        </p>
      )}

      <div className="mb-4 flex flex-wrap items-end gap-3 rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="space-y-1">
          <label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Source</label>
          <select
            value={sourceFilter}
            onChange={(event) => setSourceFilter(event.target.value as VideoSource | "")}
            className="rounded-lg border border-zinc-300 bg-white px-2.5 py-1.5 text-sm capitalize text-zinc-900 outline-none focus:border-indigo-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
          >
            <option value="">All</option>
            {SOURCES.map((source) => (
              <option key={source} value={source}>
                {source}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-1">
          <label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Camera</label>
          <select
            value={cameraFilter}
            onChange={(event) => setCameraFilter(event.target.value)}
            className="rounded-lg border border-zinc-300 bg-white px-2.5 py-1.5 text-sm text-zinc-900 outline-none focus:border-indigo-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
          >
            <option value="">All</option>
            {cameras.map((camera) => (
              <option key={camera.id} value={camera.id}>
                {camera.name}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-1">
          <label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">From</label>
          <input
            type="date"
            value={fromFilter}
            onChange={(event) => setFromFilter(event.target.value)}
            className="rounded-lg border border-zinc-300 bg-white px-2.5 py-1.5 text-sm text-zinc-900 outline-none focus:border-indigo-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">To</label>
          <input
            type="date"
            value={toFilter}
            onChange={(event) => setToFilter(event.target.value)}
            className="rounded-lg border border-zinc-300 bg-white px-2.5 py-1.5 text-sm text-zinc-900 outline-none focus:border-indigo-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
          />
        </div>

        {filtersActive && (
          <button
            type="button"
            onClick={() => {
              setSourceFilter("");
              setCameraFilter("");
              setFromFilter("");
              setToFilter("");
            }}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-zinc-500 transition hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            Clear filters
          </button>
        )}
      </div>

      {listError && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
          {listError}
        </p>
      )}

      {videos === null ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading videos…</p>
      ) : videos.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-zinc-300 bg-white p-8 text-center dark:border-zinc-700 dark:bg-zinc-900">
          <h2 className="font-medium text-zinc-900 dark:text-zinc-50">
            {filtersActive ? "No videos match these filters" : "No videos yet"}
          </h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-zinc-500 dark:text-zinc-400">
            {filtersActive
              ? "Try clearing a filter to widen the search."
              : "Upload a recording to see it appear here with its duration and size."}
          </p>
          {!filtersActive && (
            <button
              type="button"
              onClick={openFilePicker}
              className="mt-5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500"
            >
              Upload Video
            </button>
          )}
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
              <tr>
                <th className="px-4 py-3 font-medium">Filename</th>
                <th className="px-4 py-3 font-medium">Camera</th>
                <th className="px-4 py-3 font-medium">Duration</th>
                <th className="px-4 py-3 font-medium">Size</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Uploaded</th>
                <th className="px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {videos.map((video) => (
                <tr key={video.id}>
                  <td className="p-0 font-medium text-zinc-900 dark:text-zinc-50">
                    <Link href={`/videos/${video.id}`} className="block px-4 py-3 hover:underline">
                      {video.filename}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">
                    {video.camera_id != null ? (cameraNames.get(video.camera_id) ?? `#${video.camera_id}`) : "—"}
                  </td>
                  <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">
                    {formatDuration(video.duration_s)}
                  </td>
                  <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">{formatSize(video.size_bytes)}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={video.status} />
                  </td>
                  <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">
                    {formatDate(video.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    {confirmDeleteId === video.id ? (
                      <span className="flex items-center gap-1">
                        <button
                          type="button"
                          disabled={deletingId === video.id}
                          onClick={() => handleDelete(video)}
                          className="rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white transition hover:bg-red-500 disabled:opacity-50"
                        >
                          Confirm
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(null)}
                          className="rounded-md px-2 py-1 text-xs font-medium text-zinc-500 transition hover:bg-zinc-100 dark:hover:bg-zinc-800"
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(video.id)}
                        className="rounded-md px-2 py-1 text-xs font-medium text-red-600 transition hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40"
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
