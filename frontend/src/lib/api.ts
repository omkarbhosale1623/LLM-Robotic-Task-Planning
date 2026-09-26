// Typed API client targeting the FastAPI backend at NEXT_PUBLIC_API_BASE_URL.
// Every request carries the Supabase access token as `Authorization: Bearer`.

import { getAccessToken } from "./auth-token";
import type {
  BenchmarkReport,
  Capabilities,
  ExecutionResponse,
  HealthResponse,
  PlanAndRunResponse,
  PlannerMode,
  PlanResponse,
  PlanStep,
  WorldState,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** WebSocket base URL derived from the HTTP base URL. */
export function wsBaseUrl(): string {
  return API_BASE_URL.replace(/^http/, "ws");
}

/** WebSocket URL for a path, appending the Supabase token as a query param. */
export function wsUrl(path: string): string {
  const base = `${wsBaseUrl()}${path}`;
  const token = getAccessToken();
  if (!token) return base;
  const sep = base.includes("?") ? "&" : "?";
  return `${base}${sep}token=${encodeURIComponent(token)}`;
}

interface ApiErrorBody {
  error?: { type: string; message: string; detail?: unknown };
}

export class ApiError extends Error {
  readonly status: number;
  readonly type: string;
  constructor(status: number, type: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.type = type;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    ...init,
    headers,
  });
  if (!res.ok) {
    let detail: ApiErrorBody = {};
    try {
      detail = (await res.json()) as ApiErrorBody;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(
      res.status,
      detail.error?.type ?? "http_error",
      detail.error?.message ?? `Request failed with status ${res.status}`,
    );
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<HealthResponse>("/health"),

  getWorld: () => request<WorldState>("/api/v1/world"),

  resetWorld: (scene: string) =>
    request<WorldState>("/api/v1/world/reset", {
      method: "POST",
      body: JSON.stringify({ scene }),
    }),

  listScenes: () => request<{ scenes: string[] }>("/api/v1/world/scenes"),

  plan: (instruction: string, mode: PlannerMode, useCurrentWorld = true) =>
    request<PlanResponse>("/api/v1/plan", {
      method: "POST",
      body: JSON.stringify({
        instruction,
        mode,
        use_current_world: useCurrentWorld,
      }),
    }),

  execute: (plan: PlanStep[], instruction = "", resetScene?: string) =>
    request<ExecutionResponse>("/api/v1/execute", {
      method: "POST",
      body: JSON.stringify({ plan, instruction, reset_scene: resetScene ?? null }),
    }),

  planAndRun: (instruction: string, mode: PlannerMode, resetScene?: string) =>
    request<PlanAndRunResponse>("/api/v1/plan-and-run", {
      method: "POST",
      body: JSON.stringify({
        instruction,
        mode,
        reset_scene: resetScene ?? null,
      }),
    }),

  benchmark: (mode: PlannerMode) =>
    request<BenchmarkReport>(`/api/v1/benchmark?mode=${mode}`),

  capabilities: () => request<Capabilities>("/api/v1/capabilities"),
};
