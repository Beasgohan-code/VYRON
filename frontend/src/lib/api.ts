import type {
  ActionResult,
  ApiHealth,
  ApiKeyOptions,
  ApiKeyPayload,
  AppState,
  HomePayload,
  JournalPayload,
  Playlist,
  Room,
  Track,
} from "./types";

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData?: string;
        ready?: () => void;
        expand?: () => void;
        close?: () => void;
        requestFullscreen?: () => void;
        exitFullscreen?: () => void;
        setHeaderColor?: (color: string) => void;
        setBackgroundColor?: (color: string) => void;
        openTelegramLink?: (url: string) => void;
        openLink?: (url: string) => void;
        HapticFeedback?: {
          impactOccurred?: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
          notificationOccurred?: (type: "error" | "success" | "warning") => void;
        };
      };
    };
  }
}

export const telegram = () => window.Telegram?.WebApp;

const TOKEN_KEY = "vyron:token";
const OWNER_KEY = "vyron:owner-token";

const params = new URLSearchParams(window.location.search);
if (params.get("t")) {
  localStorage.setItem(TOKEN_KEY, params.get("t") as string);
}
if (params.get("ot")) {
  localStorage.setItem(OWNER_KEY, params.get("ot") as string);
}

// Keep tokens out of the address bar once they are stored, so screenshots and
// shared links do not leak access.
if ((params.get("t") || params.get("ot")) && window.history?.replaceState) {
  params.delete("t");
  params.delete("ot");
  const query = params.toString();
  window.history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
}

export function token(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

/** Signed owner token from `/apitoken` (`?ot=…` links). */
export function ownerToken(): string {
  return localStorage.getItem(OWNER_KEY) ?? "";
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Init-Data": telegram()?.initData ?? "",
      "X-Vyron-Token": token(),
      ...(ownerToken() ? { "X-Owner-Token": ownerToken() } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });

  let payload: Record<string, unknown> = {};
  try {
    payload = (await response.json()) as Record<string, unknown>;
  } catch {
    payload = {};
  }

  if (!response.ok || payload.ok === false) {
    throw new ApiError(
      typeof payload.error === "string" ? payload.error : `request failed (${response.status})`,
      response.status
    );
  }
  return payload as T;
}

export const api = {
  state: () => request<AppState>("/api/state"),

  home: () => request<HomePayload>("/api/home"),

  search: (query: string, limit = 12) =>
    request<{ results: Track[]; preview?: boolean }>("/api/search", { query, limit }),

  mix: (key: string) => request<{ tracks: Track[]; preview?: boolean }>(`/api/mix?key=${encodeURIComponent(key)}`),

  rooms: () => request<{ rooms: Room[]; preview?: boolean }>("/api/rooms"),

  playlists: () => request<{ playlists: Playlist[]; preview?: boolean }>("/api/playlists"),

  /** Owner journal — `since` makes it a cheap live tail. */
  logs: (options: { since?: number; level?: string; scope?: string; n?: number } = {}) => {
    const params = new URLSearchParams();
    if (options.since) params.set("since", String(options.since));
    if (options.level && options.level !== "all") params.set("level", options.level);
    if (options.scope) params.set("scope", options.scope);
    if (options.n) params.set("n", String(options.n));
    const query = params.toString();
    return request<JournalPayload>(`/api/logs${query ? `?${query}` : ""}`);
  },

  logsAction: (action: "clear" | "export") =>
    request<{ ok: boolean; cleared?: number; file?: string; path?: string }>("/api/logs", { action }),

  lyrics: (title: string, artist = "", duration = 0) =>
    request<{ ok: boolean; text?: string; synced?: boolean; lines?: { time: number; text: string }[] }>(
      "/api/lyrics",
      { title, artist, duration }
    ),

  action: <T = ActionResult>(action: string, value?: unknown) =>
    request<T & ActionResult>("/api/action", { action, value }),

  /* ── music API (Eldian-compatible, same origin) ─────────────────────── */
  keys: () => request<ApiKeyPayload>("/api/keys"),

  createKey: (options: string | ApiKeyOptions = "web") =>
    request<ApiKeyPayload>("/api/keys", {
      action: "create",
      ...(typeof options === "string" ? { label: options } : options),
    }),

  revokeKey: (id: string) =>
    request<ApiKeyPayload & { error?: string }>("/api/keys", { action: "revoke", id }),

  rotateKey: (id: string) =>
    request<ApiKeyPayload & { error?: string }>("/api/keys", { action: "rotate", id }),

  apiHealth: async (): Promise<ApiHealth> => {
    const response = await fetch("/v1/health", { credentials: "same-origin" });
    if (!response.ok) throw new ApiError(`music api unavailable (${response.status})`, response.status);
    return (await response.json()) as ApiHealth;
  },
};

export function haptic(style: "light" | "medium" | "heavy" | "soft" = "light"): void {
  try {
    telegram()?.HapticFeedback?.impactOccurred?.(style);
  } catch {
    /* Telegram may not expose haptics on every platform */
  }
}

export function notify(type: "error" | "success" | "warning"): void {
  try {
    telegram()?.HapticFeedback?.notificationOccurred?.(type);
  } catch {
    /* noop */
  }
}
