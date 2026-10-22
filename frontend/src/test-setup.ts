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

export const demoState = {
  ok: true,
  preview: true,
  version: "preview",
  bot: "VyronMusicBot",
  streaming: true,
  user: { id: 1, name: "Test Listener", username: "tester" },
  chat: { id: -1001, title: "Test Chat", is_group: true },
  now: {
    id: "d1",
    title: "Midnight Drive",
    uploader: "Lumen",
    duration: 212,
    elapsed: 74,
    paused: false,
    source: "youtube",
    thumbnail: "/app/static/covers/04.jpg",
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

export const demoHome = {
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

const json = (payload: unknown) =>
  Promise.resolve({
    ok: true,
    status: 200,
    json: async () => payload,
  } as Response);

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/home")) return json(demoHome);
    if (url.includes("/api/rooms")) return json({ ok: true, rooms: [] });
    if (url.includes("/api/playlists")) return json({ ok: true, playlists: demoState.playlists });
    if (url.includes("/api/search")) return json({ ok: true, results: demoHome.trending });
    if (url.includes("/api/action")) return json({ ok: true });
    return json(demoState);
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});
