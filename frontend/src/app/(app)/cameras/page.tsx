"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";

import { useAuth } from "@/lib/auth-context";
import {
  ApiError,
  type Camera,
  type CameraDomain,
  type CameraInput,
  type CameraStatus,
  type CameraTestResult,
  createCamera,
  deleteCamera,
  listCameras,
  testCameraConnection,
  updateCamera,
} from "@/lib/api-client";

const DOMAINS: CameraDomain[] = ["surveillance", "sports", "traffic"];

const EMPTY_FORM: CameraInput = {
  name: "",
  rtsp_url: "",
  location: "",
  group: "",
  domain: "surveillance",
};

const STATUS_STYLES: Record<CameraStatus, string> = {
  registered: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  connected: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
  unreachable: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400",
  disabled: "bg-zinc-100 text-zinc-400 dark:bg-zinc-800 dark:text-zinc-600",
};

function StatusBadge({ status }: { status: CameraStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_STYLES[status]}`}
    >
      {status}
    </span>
  );
}

function formatLastSeen(value: string | null): string {
  if (!value) return "Never";
  return new Date(value).toLocaleString();
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export default function CamerasPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [cameras, setCameras] = useState<Camera[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [formCameraId, setFormCameraId] = useState<number | null>(null);
  const [form, setForm] = useState<CameraInput>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<CameraTestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  const [rowBusyId, setRowBusyId] = useState<number | null>(null);
  const [rowTestResult, setRowTestResult] = useState<{ id: number; result: CameraTestResult } | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  async function refresh() {
    try {
      const rows = await listCameras();
      setCameras(rows);
      setListError(null);
    } catch (err) {
      setListError(errorMessage(err, "could not load cameras"));
    }
  }

  useEffect(() => {
    listCameras()
      .then((rows) => {
        setCameras(rows);
        setListError(null);
      })
      .catch((err) => {
        setListError(errorMessage(err, "could not load cameras"));
      });
  }, []);

  function openAddForm() {
    setFormCameraId(null);
    setForm(EMPTY_FORM);
    setTestResult(null);
    setFormError(null);
    setFormOpen(true);
  }

  function openEditForm(camera: Camera) {
    setFormCameraId(camera.id);
    // rtsp_url isn't part of the list/detail shape (OMNI-203) — left blank
    // here on purpose; a blank field means "leave the stream address alone"
    // on save, matching the PATCH endpoint's partial-update semantics.
    setForm({
      name: camera.name,
      rtsp_url: "",
      location: camera.location,
      group: camera.group,
      domain: camera.domain,
    });
    setTestResult(null);
    setFormError(null);
    setFormOpen(true);
  }

  function closeForm() {
    setFormOpen(false);
  }

  function patchPayload(): Partial<CameraInput> {
    const payload: Partial<CameraInput> = {};
    if (form.name) payload.name = form.name;
    if (form.rtsp_url) payload.rtsp_url = form.rtsp_url;
    if (form.location) payload.location = form.location;
    if (form.group) payload.group = form.group;
    if (form.domain) payload.domain = form.domain;
    return payload;
  }

  // Creates the camera on first use (or patches an already-created one with
  // whatever the user has changed since), returning its id either way.
  async function saveDraft(): Promise<number> {
    if (formCameraId !== null) {
      await updateCamera(formCameraId, patchPayload());
      return formCameraId;
    }
    const created = await createCamera(form);
    setFormCameraId(created.id);
    return created.id;
  }

  async function handleTestConnection() {
    setFormError(null);
    setTesting(true);
    try {
      const id = await saveDraft();
      const result = await testCameraConnection(id);
      setTestResult(result);
      await refresh();
    } catch (err) {
      setFormError(errorMessage(err, "could not test this camera"));
    } finally {
      setTesting(false);
    }
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setSaving(true);
    try {
      await saveDraft();
      await refresh();
      setFormOpen(false);
    } catch (err) {
      setFormError(errorMessage(err, "could not save this camera"));
    } finally {
      setSaving(false);
    }
  }

  async function handleRowTest(camera: Camera) {
    setRowBusyId(camera.id);
    setRowTestResult(null);
    try {
      const result = await testCameraConnection(camera.id);
      setRowTestResult({ id: camera.id, result });
      await refresh();
    } catch (err) {
      setRowTestResult({
        id: camera.id,
        result: { reachable: false, resolution: null, fps: null, error: errorMessage(err, "test failed") },
      });
    } finally {
      setRowBusyId(null);
    }
  }

  async function handleDisable(camera: Camera) {
    setRowBusyId(camera.id);
    try {
      await updateCamera(camera.id, { status: "disabled" });
      await refresh();
    } catch (err) {
      setListError(errorMessage(err, "could not disable this camera"));
    } finally {
      setRowBusyId(null);
    }
  }

  async function handleDelete(camera: Camera) {
    setRowBusyId(camera.id);
    try {
      await deleteCamera(camera.id);
      await refresh();
    } catch (err) {
      setListError(errorMessage(err, "could not delete this camera"));
    } finally {
      setRowBusyId(null);
      setConfirmDeleteId(null);
    }
  }

  const canSaveNewCamera =
    form.name.trim() !== "" &&
    form.rtsp_url.trim() !== "" &&
    form.location.trim() !== "" &&
    form.group.trim() !== "";
  const canSave = formCameraId !== null || canSaveNewCamera;

  return (
    <main className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Cameras</h1>
        {isAdmin && (
          <button
            type="button"
            onClick={openAddForm}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500"
          >
            Add Camera
          </button>
        )}
      </div>

      {listError && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
          {listError}
        </p>
      )}

      {cameras === null ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading cameras…</p>
      ) : cameras.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-zinc-300 bg-white p-8 text-center dark:border-zinc-700 dark:bg-zinc-900">
          <h2 className="font-medium text-zinc-900 dark:text-zinc-50">No cameras registered yet</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-zinc-500 dark:text-zinc-400">
            {isAdmin
              ? "Register a camera with its RTSP address. Don't have a real camera handy? The local simulator serves ten looping feeds — try:"
              : "No cameras have been registered yet. An administrator can add one."}
          </p>
          {isAdmin && (
            <p className="mx-auto mt-2 max-w-md">
              <code className="rounded bg-zinc-100 px-2 py-1 text-xs text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                rtsp://mediamtx:8554/cam01
              </code>
            </p>
          )}
          {isAdmin && (
            <button
              type="button"
              onClick={openAddForm}
              className="mt-5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500"
            >
              Add Camera
            </button>
          )}
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
              <tr>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Location</th>
                <th className="px-4 py-3 font-medium">Group</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Last seen</th>
                {isAdmin && <th className="px-4 py-3 font-medium">Actions</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {cameras.map((camera) => (
                <tr key={camera.id}>
                  <td className="p-0 font-medium text-zinc-900 dark:text-zinc-50">
                    <Link href={`/cameras/${camera.id}`} className="block px-4 py-3 hover:underline">
                      {camera.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">{camera.location}</td>
                  <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">{camera.group}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={camera.status} />
                    {rowTestResult?.id === camera.id && (
                      <p
                        className={`mt-1 text-xs ${
                          rowTestResult.result.reachable
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-red-600 dark:text-red-400"
                        }`}
                      >
                        {rowTestResult.result.reachable
                          ? `${rowTestResult.result.resolution} @ ${rowTestResult.result.fps} fps`
                          : rowTestResult.result.error}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">
                    {formatLastSeen(camera.last_seen_at)}
                  </td>
                  {isAdmin && (
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          disabled={rowBusyId === camera.id}
                          onClick={() => handleRowTest(camera)}
                          className="rounded-md px-2 py-1 text-xs font-medium text-indigo-600 transition hover:bg-indigo-50 disabled:opacity-50 dark:text-indigo-400 dark:hover:bg-indigo-950/40"
                        >
                          Test
                        </button>
                        <button
                          type="button"
                          onClick={() => openEditForm(camera)}
                          className="rounded-md px-2 py-1 text-xs font-medium text-zinc-600 transition hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
                        >
                          Edit
                        </button>
                        {camera.status !== "disabled" && (
                          <button
                            type="button"
                            disabled={rowBusyId === camera.id}
                            onClick={() => handleDisable(camera)}
                            className="rounded-md px-2 py-1 text-xs font-medium text-zinc-600 transition hover:bg-zinc-100 disabled:opacity-50 dark:text-zinc-300 dark:hover:bg-zinc-800"
                          >
                            Disable
                          </button>
                        )}
                        {confirmDeleteId === camera.id ? (
                          <span className="flex items-center gap-1">
                            <button
                              type="button"
                              disabled={rowBusyId === camera.id}
                              onClick={() => handleDelete(camera)}
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
                            onClick={() => setConfirmDeleteId(camera.id)}
                            className="rounded-md px-2 py-1 text-xs font-medium text-red-600 transition hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40"
                          >
                            Delete
                          </button>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {formOpen && (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl border border-zinc-200 bg-white p-6 shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="mb-4 font-medium text-zinc-900 dark:text-zinc-50">
              {formCameraId !== null ? "Edit camera" : "Add camera"}
            </h2>

            <form onSubmit={handleSave} className="space-y-3">
              <div className="space-y-1">
                <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Name</label>
                <input
                  required
                  value={form.name}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/30 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                />
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  RTSP address{formCameraId !== null && " (leave blank to keep the current one)"}
                </label>
                <input
                  required={formCameraId === null}
                  placeholder="rtsp://mediamtx:8554/cam01"
                  value={form.rtsp_url}
                  onChange={(event) => setForm({ ...form, rtsp_url: event.target.value })}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/30 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Location</label>
                  <input
                    required
                    value={form.location}
                    onChange={(event) => setForm({ ...form, location: event.target.value })}
                    className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/30 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Group</label>
                  <input
                    required
                    value={form.group}
                    onChange={(event) => setForm({ ...form, group: event.target.value })}
                    className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/30 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Domain</label>
                <select
                  value={form.domain}
                  onChange={(event) => setForm({ ...form, domain: event.target.value as CameraDomain })}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm capitalize text-zinc-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/30 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                >
                  {DOMAINS.map((domain) => (
                    <option key={domain} value={domain}>
                      {domain}
                    </option>
                  ))}
                </select>
              </div>

              {testResult && (
                <p
                  className={`rounded-lg px-3 py-2 text-sm ${
                    testResult.reachable
                      ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400"
                      : "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400"
                  }`}
                >
                  {testResult.reachable
                    ? `Reachable — ${testResult.resolution} at ${testResult.fps} fps`
                    : `Not reachable — ${testResult.error}`}
                </p>
              )}

              {formError && (
                <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
                  {formError}
                </p>
              )}

              <div className="flex items-center justify-between gap-2 pt-2">
                <button
                  type="button"
                  onClick={handleTestConnection}
                  disabled={testing || !canSave}
                  className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
                >
                  {testing ? "Testing…" : "Test Connection"}
                </button>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={closeForm}
                    className="rounded-lg px-4 py-2 text-sm font-medium text-zinc-500 transition hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={saving || !canSave}
                    className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {saving ? "Saving…" : "Save"}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}
