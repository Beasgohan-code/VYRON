import type {
  ApiKeyUpdate,
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

/** Keep a chat-scoped token so the app can drive a group player later. */
export function setToken(value: string): void {
  if (value) localStorage.setItem(TOKEN_KEY, value);
  else localStorage.removeItem(TOKEN_KEY);
}

/** Signed owner token from `/apitoken` (`?ot=…` links). */
export function ownerToken(): string {
  return localStorage.getItem(OWNER_KEY) ?? "";
}

/** Paste an owner token (from `/apitoken`) to unlock a plain browser. */
export function setOwnerToken(value: string): void {
  if (value) localStorage.setItem(OWNER_KEY, value);
  else localStorage.removeItem(OWNER_KEY);
}

/** How long a request may take before we assume the deployment is asleep. */
const REQUEST_TIMEOUT_MS = 14000;
const COLD_START_TIMEOUT_MS = 26000;

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  // A free Render instance can take ~40 s to wake. Without a timeout the
  // request (and the boot screen behind it) simply hangs forever, which looks
  // like a broken app rather than a starting one.
  const long = path.includes("/search") || path.includes("/mix");
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  const limit = long ? COLD_START_TIMEOUT_MS : REQUEST_TIMEOUT_MS;
  const timer = controller ? window.setTimeout(() => controller.abort(), limit) : 0;

  let response: Response;
  try {
    response = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Init-Data": telegram()?.initData ?? "",
        "X-Vyron-Token": token(),
        ...(ownerToken() ? { "X-Owner-Token": ownerToken() } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      signal: controller?.signal,
    });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") {
      throw new ApiError("the server is still starting — give it a moment", 0);
    }
    throw new ApiError(
      error instanceof Error ? error.message : "the server could not be reached",
      0
    );
  } finally {
    window.clearTimeout(timer);
  }

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

  /** Ask the server for a chat-scoped token for a room the user administers. */
  attachRoom: (chatId: number) =>
    request<{ ok: boolean; chat_id: number; token: string }>("/api/room", { chat_id: chatId }),

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

  /** SSE endpoint — the journal, live. EventSource cannot send headers, so the
   *  credentials ride in the query string (initData / signed token / owner
   *  token), exactly what `_identify` already accepts. */
  logStreamUrl: (options: { level?: string; scope?: string } = {}) => {
    const params = new URLSearchParams();
    if (options.level && options.level !== "all") params.set("level", options.level);
    if (options.scope) params.set("scope", options.scope);
    const init = telegram()?.initData ?? "";
    if (init) params.set("init_data", init);
    const tok = token();
    if (tok) params.set("t", tok);
    const owner = ownerToken();
    if (owner) params.set("ot", owner);
    const query = params.toString();
    return `/api/logs/stream${query ? `?${query}` : ""}`;
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

  /* ── music API + download API (same origin) ─────────────────────────── */
  keys: () => request<ApiKeyPayload>("/api/keys"),

  createKey: (options: string | ApiKeyOptions = "web") =>
    request<ApiKeyPayload>("/api/keys", {
      action: "create",
      ...(typeof options === "string" ? { label: options } : options),
    }),

  revokeKey: (id: string) =>
    request<ApiKeyPayload & { error?: string }>("/api/keys", { action: "revoke", id }),

  updateKey: (change: ApiKeyUpdate | string, patch: Omit<ApiKeyUpdate, "id"> = {}) =>
    request<ApiKeyPayload & { error?: string }>("/api/keys", {
      action: "update",
      ...(typeof change === "string" ? { id: change, ...patch } : change),
    }),

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
