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

export async function deleteVideo(id: number): Promise<{ id: number; deleted: boolean }> {
  return request(`/videos/${id}`, { method: "DELETE" });
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
