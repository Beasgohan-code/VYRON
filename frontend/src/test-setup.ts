import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

/* jsdom lacks these; components call them without guards. */
class Observer {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}

globalThis.ResizeObserver = globalThis.ResizeObserver ?? (Observer as never);
globalThis.IntersectionObserver = globalThis.IntersectionObserver ?? (Observer as never);
window.scrollTo = window.scrollTo ?? (() => undefined);
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});

export const fixtureState = {
  ok: true,
  preview: true,
  version: "preview",
  bot: "VyronMusicBot",
  streaming: true,
  user: { id: 1, name: "Test Listener", username: "tester", owner: true, access: "preview" },
  owner: true,
  chat: { id: -1001, title: "Test Chat", is_group: true },
  now: {
    id: "d1",
    title: "Midnight Drive",
    uploader: "Lumen",
    duration: 212,
    elapsed: 74,
    paused: false,
    source: "youtube",
    thumbnail: "",
  },
  queue: [
    { id: "d2", index: 1, title: "Neon Skyline", uploader: "VYRON Sessions", duration: 198 },
    { id: "d3", index: 2, title: "Slow Motion", uploader: "Aria Vale", duration: 241 },
  ],
  settings: { volume: 100, loop: "off", autoplay: true, always_on: false, shuffle: false, effects: [] },
  favorites: [{ id: "f1", title: "Saved track", uploader: "Artist", duration: 180 }],
  history: [{ id: "h1", title: "Yesterday's song", uploader: "Artist", duration: 201 }],
  playlists: [{ id: "p1", name: "Late Night", count: 2, duration: 400, covers: [], tracks: [] }],
};

export const fixtureHome = {
  hero: { headline: "Music hits different here.", subline: "All in one place.", cover: "/app/static/covers/07.jpg" },
  trending: [
    { id: "t1", title: "Neon Skyline", uploader: "VYRON Sessions", duration: 198, query: "neon skyline" },
    { id: "t2", title: "Slow Motion", uploader: "Aria Vale", duration: 241 },
  ],
  shelves: [
    {
      key: "daily",
      title: "Daily Mix",
      glyph: "sun",
      kind: "mix",
      tracks: [{ id: "m1", title: "Golden Hour", uploader: "Sable", duration: 233 }],
    },
  ],
  moods: [
    { key: "chill", title: "Chill" },
    { key: "focus", title: "Focus" },
  ],
};

export const fixtureKeys = {
  ok: true,
  preview: true,
  base: "http://localhost:8099",
  docs: "http://localhost:8099/v1/docs",
  openapi: "http://localhost:8099/v1/openapi.json",
  is_owner: true,
  version: "2.0",
  scopes: ["read", "search", "download", "admin"],
  default_scopes: ["read", "search", "download"],
  metrics: {
    requests: 12,
    downloads: 4,
    bytes_served: 5200000,
    rate_limited: 0,
    uptime_seconds: 420,
    latency_ms: { avg: 12, p50: 9, p95: 24, p99: 41 },
  },
  keys: [
    {
      id: "key_fixture",
      prefix: "vyrn_fixture",
      masked: "vyrn_fix…0000",
      label: "api-bot",
      scopes: ["read", "search", "download"],
      active: true,
      uses: 12,
      bytes: 5200000,
      last_used_at: 1759999999,
    },
  ],
  stats: {
    enabled: true,
    open: true,
    keys: 1,
    keys_total: 1,
    requests: 12,
    bytes: 5200000,
    rate_limit: 30,
    storage: "mongo",
    version: "2.0",
  },
};

export const fixtureApiHealth = {
  status: "ok",
  ok: true,
  service: "vyron-music-api",
  version: "preview",
  uptime: 12,
  ready: true,
  auth_required: false,
  rate_limit: 30,
  keys: 1,
  endpoints: ["/v1/health", "/v1/search"],
};

export const fixtureLogs = {
  ok: true,
  events: [
    { seq: 1, ts: 1759999900, level: "info", scope: "boot", message: "VYRON preview online", meta: {} },
    { seq: 2, ts: 1759999950, level: "warn", scope: "database", message: "MongoDB unavailable", meta: {} },
    {
      seq: 3,
      ts: 1759999990,
      level: "error",
      scope: "player",
      message: "stream start failed in -1001",
      meta: { type: "StreamError", traceback: "StreamError: boom" },
    },
  ],
  stats: { seq: 3, buffered: 3, counts: { info: 1, warn: 1, error: 1 }, errors: 1, warnings: 1, uptime: 420, file: "data/journal.jsonl" },
  system: {
    version: "preview",
    uptime: 420,
    storage: "mongo",
    streaming: true,
    resolver: true,
    downloader: true,
    handlers: 23,
    chats: 2,
    playing: 1,
    watchdog: { checks: 9, reconnects: 0, last: null, last_error: "" },
    keepalive: { enabled: true, runs: 4, last_ok: 1759999990, last_status: 200 },
  },
};

export const json = (payload: unknown) =>
  Promise.resolve({
    ok: true,
    status: 200,
    json: async () => payload,
  } as Response);

/** Fake the whole API — pass overrides to test a variant of the state. */
export function stubApi(overrides: Record<string, unknown> = {}) {
  const state = { ...fixtureState, ...overrides };
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/home")) return json(fixtureHome);
    if (url.includes("/api/rooms")) return json({ ok: true, rooms: [] });
    if (url.includes("/api/playlists")) return json({ ok: true, playlists: fixtureState.playlists });
    if (url.includes("/api/search")) return json({ ok: true, results: fixtureHome.trending });
    if (url.includes("/api/action")) return json({ ok: true });
    if (url.includes("/api/logs")) return json(fixtureLogs);
    if (url.includes("/api/keys")) return json(fixtureKeys);
    if (url.includes("/v1/health")) return json(fixtureApiHealth);
    return json(state);
  }));
}

beforeEach(() => {
  stubApi();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});
