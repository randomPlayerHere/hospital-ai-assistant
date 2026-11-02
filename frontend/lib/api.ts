import createClient from "openapi-fetch";
import type { components, paths } from "./api-types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export type Schemas = components["schemas"];
export type Role = "admin" | "doctor" | "staff" | "patient";

const REFRESH_KEY = "hospital.refresh";
let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onLoggedOut: (() => void) | null = null;

export function setLogoutHandler(fn: (() => void) | null) {
  onLoggedOut = fn;
}

function store(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function setTokens(pair: { access_token?: string | null; refresh_token?: string | null }) {
  if (pair.access_token && pair.refresh_token) {
    accessToken = pair.access_token;
    store()?.setItem(REFRESH_KEY, pair.refresh_token);
  }
}

export function clearTokens() {
  accessToken = null;
  store()?.removeItem(REFRESH_KEY);
}

export function getRefreshToken(): string | null {
  return store()?.getItem(REFRESH_KEY) ?? null;
}

export function hasAccessToken() {
  return accessToken !== null;
}

/** Exchange the refresh token (rotating). Concurrent callers share one request. */
export function refreshTokens(): Promise<boolean> {
  if (refreshing) return refreshing;
  const refresh = getRefreshToken();
  refreshing = (async () => {
    try {
      const res = await fetch(`${API_URL}/api/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(refresh ? { refresh_token: refresh } : {}),
      });
      if (!res.ok) {
        clearTokens();
        return false;
      }
      setTokens(await res.json());
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

async function authFetch(req: Request): Promise<Response> {
  const retry = req.clone();
  if (accessToken) req.headers.set("Authorization", `Bearer ${accessToken}`);
  const res = await fetch(req, { credentials: "include" });
  const isAuthCall = new URL(req.url).pathname.startsWith("/api/auth/");
  if (res.status === 401 && !isAuthCall) {
    if (await refreshTokens()) {
      retry.headers.set("Authorization", `Bearer ${accessToken}`);
      return fetch(retry, { credentials: "include" });
    }
    onLoggedOut?.();
  }
  return res;
}

export const api = createClient<paths>({ baseUrl: API_URL, fetch: authFetch });

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function errorMessage(err: unknown): string {
  if (!err) return "Something went wrong";
  if (typeof err === "string") return err;
  const detail = (err as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg ?? "Invalid input").join("; ");
  return "Something went wrong";
}

/** Unwrap an openapi-fetch result: return data or throw ApiError with a readable message. */
export function unwrap<T>(res: { data?: T; error?: unknown; response: Response }): T {
  if (res.error !== undefined || res.data === undefined) {
    if (res.response.status === 204) return undefined as T;
    throw new ApiError(res.response.status, errorMessage(res.error));
  }
  return res.data;
}

export async function download(path: string, filename: string) {
  const res = await authFetch(new Request(`${API_URL}${path}`));
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function uploadDocument(patientId: string, file: File, docType: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("doc_type", docType);
  const res = await authFetch(
    new Request(`${API_URL}/api/patients/${patientId}/documents`, { method: "POST", body: form }),
  );
  if (!res.ok) throw new ApiError(res.status, errorMessage(await res.json().catch(() => null)));
  return (await res.json()) as Schemas["DocumentOut"];
}

export const HOME: Record<Role, string> = {
  admin: "/admin",
  doctor: "/doctor",
  staff: "/reception",
  patient: "/patient",
};
