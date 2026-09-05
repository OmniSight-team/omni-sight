import type { Role } from "@/lib/nav";

// Relative by default — same-origin, proxied to the backend by next.config.ts
// (direct dev) or by nginx (OMNI-111), so traffic never has to leave the
// connection the browser already secured. Only set NEXT_PUBLIC_API_URL to an
// absolute URL if the frontend and API are genuinely on different origins.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
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

  const response = await fetch(`${API_URL}${path}`, { ...options, headers });

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
