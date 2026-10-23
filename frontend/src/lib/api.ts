import type {
  ActionResult,
  ApiHealth,
  ApiKeyOptions,
  ApiKeyPayload,
  AppState,
  HomePayload,
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

const params = new URLSearchParams(window.location.search);
if (params.get("t")) {
  localStorage.setItem(TOKEN_KEY, params.get("t") as string);
}

export function token(): string {
  return params.get("t") ?? localStorage.getItem(TOKEN_KEY) ?? "";
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
