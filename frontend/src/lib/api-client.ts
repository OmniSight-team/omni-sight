import type { Role } from "@/lib/nav";

// Relative by default — same-origin, proxied to the backend by next.config.ts
// (direct dev) or by nginx (OMNI-111), so traffic never has to leave the
// connection the browser already secured. Only set NEXT_PUBLIC_API_URL to an
// absolute URL if the frontend and API are genuinely on different origins.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
// Every call goes through /api/* (OMNI-208) — a bare resource path like
// /cameras would collide with the frontend's own /cameras screen, since
// that's both an API path and a page path on the same origin.
const API_PREFIX = "/api";
const TOKEN_KEY = "omnisight_access_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_URL}${API_PREFIX}${path}`, { ...options, headers });

  const renewedToken = response.headers.get("X-Access-Token");
  if (renewedToken) setToken(renewedToken);

  const data = await response.json().catch(() => null);

  if (response.status === 401) {
    // Only a session that was already authenticated (a token was attached)
    // counts as "the session died" — an anonymous 401 (wrong login) is left
    // for the caller to handle inline.
    if (token) {
      clearToken();
      if (typeof window !== "undefined") {
        window.location.href = "/sign-in";
      }
    }
    throw new ApiError(401, data?.detail ?? "unauthorized");
  }

  if (!response.ok) {
    throw new ApiError(response.status, data?.detail ?? "request failed");
  }

  return data as T;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: Role;
}

export interface CurrentUser {
  id: number;
  email: string;
  role: Role;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const data = await request<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setToken(data.access_token);
  return data;
}

export async function logout(): Promise<void> {
  try {
    await request("/auth/logout", { method: "POST" });
  } finally {
    clearToken();
  }
}

export async function getCurrentUser(): Promise<CurrentUser> {
  return request<CurrentUser>("/auth/me");
}

export interface NavRoute {
  path: string;
  label: string;
}

// Already filtered to the current user's role by the API — the route/role
// map lives once, in omnisight_common, not duplicated here.
export async function getNavRoutes(): Promise<NavRoute[]> {
  return request<NavRoute[]>("/nav");
}

export type CameraStatus = "registered" | "connected" | "unreachable" | "disabled";
export type CameraDomain = "surveillance" | "sports" | "traffic";

export interface Camera {
  id: number;
  name: string;
  location: string;
  group: string;
  domain: CameraDomain;
  status: CameraStatus;
  last_seen_at: string | null;
}

export interface CameraInput {
  name: string;
  rtsp_url: string;
  location: string;
  group: string;
  domain: CameraDomain;
}

export interface CameraTestResult {
  reachable: boolean;
  resolution: string | null;
  fps: number | null;
  error: string | null;
}

export async function listCameras(): Promise<Camera[]> {
  return request<Camera[]>("/cameras");
}

export async function createCamera(input: CameraInput): Promise<{ id: number; status: CameraStatus }> {
  return request("/cameras", { method: "POST", body: JSON.stringify(input) });
}

export async function updateCamera(
  id: number,
  input: Partial<CameraInput> & { status?: CameraStatus },
): Promise<Camera> {
  return request<Camera>(`/cameras/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export async function deleteCamera(
  id: number,
): Promise<{ id: number; deleted: boolean; status?: CameraStatus }> {
  return request(`/cameras/${id}`, { method: "DELETE" });
}

export async function testCameraConnection(id: number): Promise<CameraTestResult> {
  return request<CameraTestResult>(`/cameras/${id}/test`, { method: "POST" });
}

export interface CameraStats {
  // Frames decoded from the stream and offered to the pipeline, and of those the
  // ones dropped because it could not keep up. Lifetime totals.
  captured: number;
  dropped: number;
  // What the gate did with the rest: captured = gated + dropped, and
  // gated = admitted + discarded. Only admitted frames are stored.
  gated: number;
  admitted: number;
  admitted_motion: number;
  admitted_heartbeat: number;
  discarded: number;
  // Frames actually gated per second, and seconds the current capture has
  // been running. Both are 0 when the camera is not being captured, so
  // `uptime_s > 0` is how the screen tells running from stopped.
  fps_effective: number;
  uptime_s: number;
}

export interface CameraFrame {
  segment_id: number;
  // When the frame was captured, as Unix time in seconds.
  timestamp_s: number;
  thumb_url: string;
}

// Starting waits for the stream's first frame, which on the simulator takes
// several seconds; the call is slow by design, not hung.
export async function startCamera(id: number): Promise<{ worker_id: string; status: string }> {
  return request(`/cameras/${id}/start`, { method: "POST" });
}

export async function stopCamera(id: number): Promise<{ status: string }> {
  return request(`/cameras/${id}/stop`, { method: "POST" });
}

export async function getCameraStats(id: number): Promise<CameraStats> {
  return request<CameraStats>(`/cameras/${id}/stats`);
}

// Oldest first. With `since` (a timestamp_s already seen): only what came after
// it. Without: the newest `limit`.
export async function listCameraFrames(
  id: number,
  options: { since?: number; limit?: number } = {},
): Promise<CameraFrame[]> {
  const params = new URLSearchParams();
  if (options.since != null) params.set("since", String(options.since));
  if (options.limit != null) params.set("limit", String(options.limit));
  const query = params.toString();
  return request<CameraFrame[]>(`/cameras/${id}/frames${query ? `?${query}` : ""}`);
}

// What a camera is doing right now (OMNI-504), worked out by the API from the
// worker it runs and the age of the newest frame, never from a stored flag.
export type LiveState = "live" | "frozen" | "offline" | "stopped";

export interface LiveCamera {
  camera_id: number;
  name: string;
  location: string;
  group_name: string;
  state: LiveState;
  // When the newest frame arrived (ISO time); null when there is no preview.
  last_frame_at: string | null;
}

// Every camera for the wall, ordered by group, then name.
export async function listLiveCameras(): Promise<LiveCamera[]> {
  return request<LiveCamera[]>("/cameras/live");
}

export type PreviewResult =
  | { kind: "frame"; blob: Blob; etag: string | null; lastModified: string | null }
  | { kind: "unchanged" }
  | { kind: "none"; reason: string };

// A camera's current frame (OMNI-503), a small JPEG. Sends the ETag of the
// frame already shown, so an unchanged frame costs a 304 and no image. Not
// through request(): the body is an image, not JSON. `cache: "no-store"` keeps
// the browser's own cache out of it, so a 304 reaches this code as a 304.
export async function fetchCameraPreview(id: number, etag: string | null): Promise<PreviewResult> {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (etag) headers.set("If-None-Match", etag);

  const response = await fetch(`${API_URL}${API_PREFIX}/cameras/${id}/preview`, { headers, cache: "no-store" });

  const renewedToken = response.headers.get("X-Access-Token");
  if (renewedToken) setToken(renewedToken);

  if (response.status === 304) return { kind: "unchanged" };
  if (response.status === 401) {
    if (token) {
      clearToken();
      window.location.href = "/sign-in";
    }
    throw new ApiError(401, "unauthorized");
  }
  if (response.status === 404) {
    const data = await response.json().catch(() => null);
    return { kind: "none", reason: data?.detail ?? "no picture" };
  }
  if (!response.ok) throw new ApiError(response.status, "preview request failed");
  return {
    kind: "frame",
    blob: await response.blob(),
    etag: response.headers.get("ETag"),
    lastModified: response.headers.get("Last-Modified"),
  };
}

// One frame of a camera's rewind buffer (OMNI-505): an admitted frame already
// stored. `frame_url` is an API path (token-checked), `thumb_url` an nginx one.
export interface BufferFrame {
  segment_id: number;
  // When the frame was captured, as Unix time in seconds.
  timestamp_s: number;
  reason: AdmissionReason;
  thumb_url: string;
  frame_url: string;
}

// The camera's admitted frames from the last `minutes` (1-10), oldest first.
export async function getCameraBuffer(id: number, minutes = 5): Promise<BufferFrame[]> {
  return request<BufferFrame[]>(`/cameras/${id}/buffer?minutes=${minutes}`);
}

// A stored frame at full size, as an image. The route checks the token, so an
// <img src> cannot load it directly; the caller makes an object URL of the blob.
export async function fetchFrameImage(frameUrl: string): Promise<Blob> {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_URL}${API_PREFIX}${frameUrl}`, { headers });
  const renewedToken = response.headers.get("X-Access-Token");
  if (renewedToken) setToken(renewedToken);
  if (response.status === 401) {
    if (token) {
      clearToken();
      window.location.href = "/sign-in";
    }
    throw new ApiError(401, "unauthorized");
  }
  if (!response.ok) throw new ApiError(response.status, "frame request failed");
  return response.blob();
}

export type VideoSource = "upload" | "camera" | "dataset";
export type VideoStatus = "uploaded" | "extracting" | "ready" | "failed";

export interface Video {
  id: number;
  filename: string;
  camera_id: number | null;
  source: VideoSource;
  duration_s: number | null;
  fps: number | null;
  width: number | null;
  height: number | null;
  size_bytes: number;
  status: VideoStatus;
  retention_until: string | null;
  created_at: string;
  segments_count: number;
  // Always set — the playback copy if ingestion made one (OMNI-308), the
  // original otherwise. Served by Nginx directly, not through this API.
  playback_url: string;
  // What produced the current admitted/discarded flags (OMNI-306). Null until
  // a first extraction has run.
  gate_cell_threshold: number | null;
}

export interface VideoListFilters {
  source?: VideoSource;
  camera_id?: number;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
}

export async function listVideos(filters: VideoListFilters = {}): Promise<Video[]> {
  const params = new URLSearchParams();
  if (filters.source) params.set("source", filters.source);
  if (filters.camera_id != null) params.set("camera_id", String(filters.camera_id));
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  if (filters.limit != null) params.set("limit", String(filters.limit));
  if (filters.offset != null) params.set("offset", String(filters.offset));
  const query = params.toString();
  return request<Video[]>(`/videos${query ? `?${query}` : ""}`);
}

export async function getVideo(id: number): Promise<Video> {
  return request<Video>(`/videos/${id}`);
}

export async function deleteVideo(id: number): Promise<{ id: number; deleted: boolean }> {
  return request(`/videos/${id}`, { method: "DELETE" });
}

// Re-scores the whole recording at a new per-cell motion threshold (OMNI-306).
// Synchronous — resolves once the new admitted/discarded flags are stored, so
// a frames fetch right after it always sees the new state.
export async function regateVideo(
  id: number,
  cellThreshold: number,
): Promise<{ admitted: number; discarded: number }> {
  return request(`/videos/${id}/gate`, {
    method: "POST",
    body: JSON.stringify({ cell_threshold: cellThreshold }),
  });
}

export type AdmissionReason = "motion" | "heartbeat";

export interface Frame {
  segment_id: number;
  frame_index: number;
  timestamp_s: number;
  motion_score: number | null;
  admitted: boolean;
  thumb_url: string | null;
  admission_reason: AdmissionReason | null;
}

export type FrameFilter = "admitted" | "discarded" | "all";

// OMNI-307's own hard cap per page. A recording can easily have more segments
// than this (any dataset clip with more than a couple hundred frames), so a
// single call is never enough on its own — see listAllFrames below.
const MAX_FRAMES_PAGE_SIZE = 200;

function frameFilterParam(filter: FrameFilter): "true" | "false" | "all" {
  return filter === "admitted" ? "true" : filter === "discarded" ? "false" : "all";
}

async function listFramesPage(videoId: number, filter: FrameFilter, offset: number): Promise<Frame[]> {
  return request<Frame[]>(
    `/videos/${videoId}/frames?admitted=${frameFilterParam(filter)}&limit=${MAX_FRAMES_PAGE_SIZE}&offset=${offset}`,
  );
}

// Loops past OMNI-307's own per-page cap so a caller always gets the *whole*
// matching set, never just the first 200 — the frame grid's counts (OMNI-309)
// have to be exact, not "however many fit in one page".
export async function listAllFrames(videoId: number, filter: FrameFilter = "all"): Promise<Frame[]> {
  const frames: Frame[] = [];
  let offset = 0;
  while (true) {
    const page = await listFramesPage(videoId, filter, offset);
    frames.push(...page);
    if (page.length < MAX_FRAMES_PAGE_SIZE) return frames;
    offset += MAX_FRAMES_PAGE_SIZE;
  }
}

export interface VideoUploadResult {
  id: number;
  filename: string;
  duration_s: number | null;
  size_mb: number;
  fps: number | null;
  status: VideoStatus;
  error: string | null;
}

// fetch() has no cross-browser way to report upload progress, so this one
// call uses XMLHttpRequest instead of the shared request() helper — the
// only reason it can't reuse that helper.
export function uploadVideo(file: File, onProgress?: (percent: number) => void): Promise<VideoUploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const token = getToken();
    xhr.open("POST", `${API_URL}${API_PREFIX}/videos/upload`);
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      const renewedToken = xhr.getResponseHeader("X-Access-Token");
      if (renewedToken) setToken(renewedToken);

      let data: unknown = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        // No JSON body (e.g. a proxy-level error page) — data stays null,
        // the fallback message below covers it.
      }

      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data as VideoUploadResult);
        return;
      }

      if (xhr.status === 401) {
        clearToken();
        window.location.href = "/sign-in";
      }

      const detail =
        data && typeof data === "object" && "detail" in data
          ? String((data as { detail: unknown }).detail)
          : "upload failed";
      reject(new ApiError(xhr.status, detail));
    };

    xhr.onerror = () => reject(new ApiError(0, "network error during upload"));

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}

// --- Lead-up windows and the hand check (OMNI-609) ----------------------------------

export type AnnotationSource = "ucf_crime_temporal" | "uca" | "ccd_binlabels";

export interface EventWindow {
  id: number;
  dataset: "ucf_crime" | "ccd";
  clip_key: string;
  event_class: string;
  annotation_source: AnnotationSource;
  split: string;
  window_start_s: number;
  window_end_s: number;
  length_s: number;
  nominal_length_s: number | null;
  shortened: boolean;
  verified: boolean | null;
  verify_reason: string | null;
  verified_by: string | null;
  verified_at: string | null;
}

export interface EventWindowDetail extends EventWindow {
  event_start_s: number;
  event_end_s: number | null;
  video_id: number | null;
  video_duration_s: number | null;
  playback_url: string | null;
}

export async function listSampleWindows(): Promise<EventWindow[]> {
  return request<EventWindow[]>("/windows");
}

export async function getWindow(id: number): Promise<EventWindowDetail> {
  return request<EventWindowDetail>(`/windows/${id}`);
}

export async function setWindowVerdict(
  id: number,
  correct: boolean,
  reason: string | null,
): Promise<EventWindowDetail> {
  return request<EventWindowDetail>(`/windows/${id}/verdict`, {
    method: "POST",
    body: JSON.stringify({ correct, reason }),
  });
}

// --- Operations Dashboard (OMNI-610 / OMNI-611) -------------------------------------

export interface DashboardSummary {
  // Cameras whose state is `live` (the same state as the wall), out of every camera.
  cameras_online: number;
  cameras_total: number;
  videos: number;
  segments: number;
  // Null until alerts exist (slice 9): no alerts is not the same as zero alerts.
  alerts_today: number | null;
  // Video bytes plus frame and thumbnail bytes, in GB (10^9 bytes).
  storage_gb: number;
  retention_days: number;
  // The oldest video retention will delete in time (dataset footage never expires).
  oldest_recording_at: string | null;
}

export interface DashboardHour {
  // The hour's start, UTC.
  hour: string;
  segments: number;
  alerts: number | null;
}

export async function getDashboardSummary(): Promise<DashboardSummary> {
  return request<DashboardSummary>("/dashboard/summary");
}

// One entry per hour, oldest first, ending with the current hour.
export async function getDashboardActivity(hours = 24): Promise<DashboardHour[]> {
  return request<DashboardHour[]>(`/dashboard/activity?hours=${hours}`);
}

export interface Dataset {
  name: string;
  domain: CameraDomain;
  videos_loaded: number;
  total: number;
  failed: number;
  status: "not_loaded" | "loading" | "partial" | "loaded";
  // The running load on this dataset, if any: clips worked through out of those queued.
  load_done: number | null;
  load_queued: number | null;
  // Lead-up windows over the whole dataset; checked and verified by the hand check.
  windows_derived: number;
  windows_checked: number;
  windows_verified: number;
}

export async function listDatasets(): Promise<Dataset[]> {
  return request<Dataset[]>("/datasets");
}

// Admin only. Queues up to `limit` clips not loaded yet; poll listDatasets for progress.
export async function loadDataset(name: string, limit: number): Promise<{ queued: number }> {
  return request(`/datasets/${name}/load`, { method: "POST", body: JSON.stringify({ limit }) });
}
