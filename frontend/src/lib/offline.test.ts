import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearOffline,
  forgetOffline,
  isKeptOffline,
  keepOffline,
  keptCount,
  offlineKey,
} from "./offline";

/**
 * A Cache that behaves like the real one for the four calls this module makes.
 * Keys are kept as absolute strings, which is exactly how `cache.match` works.
 */
function fakeCache() {
  const store = new Map<string, Response>();
  return {
    store,
    put: vi.fn(async (request: RequestInfo | URL, response: Response) => {
      store.set(String(request), response);
    }),
    match: vi.fn(async (request: RequestInfo | URL) => store.get(String(request))),
    delete: vi.fn(async (request: RequestInfo | URL) => store.delete(String(request))),
    keys: vi.fn(async () => [...store.keys()].map((url) => new Request(url))),
  };
}

let cache: ReturnType<typeof fakeCache>;

beforeEach(() => {
  cache = fakeCache();
  vi.stubGlobal("caches", { open: vi.fn(async () => cache) });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const track = { id: "abc123" };

describe("offline keying", () => {
  it("keys on the path, never the signed query", () => {
    expect(offlineKey(track)).toBe("/api/stream/abc123");
  });

  it("escapes an awkward id", () => {
    expect(offlineKey({ id: "a/b c" })).toBe("/api/stream/a%2Fb%20c");
  });

  it("has no key without an id", () => {
    expect(offlineKey({})).toBe("");
    expect(offlineKey({ id: "" })).toBe("");
  });
});

describe("keeping a track", () => {
  it("stores the whole response under the path", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("audio-bytes", { status: 200, headers: { "content-type": "audio/mpeg" } }))
    );
    const result = await keepOffline(track, "/api/stream/abc123?t=secret");
    expect(result).toEqual({ ok: true });
    const stored = cache.store.get(`${window.location.origin}/api/stream/abc123`);
    expect(stored).toBeTruthy();
    expect(stored?.headers.get("content-type")).toBe("audio/mpeg");
    expect([...cache.store.keys()].join()).not.toContain("secret");
  });

  it("refuses to store an error answer, and says why", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 502 })));
    const result = await keepOffline(track, "/api/stream/abc123");
    expect(result.ok).toBe(false);
    expect(result.reason).toContain("502");
    expect(cache.store.size).toBe(0);
  });

  it("reports a dead connection instead of throwing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("offline");
      })
    );
    const result = await keepOffline(track, "/api/stream/abc123");
    expect(result.ok).toBe(false);
    expect(result.reason).toBe("offline");
  });

  it("answers false when the browser has no Cache API", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("caches", undefined);
    expect(await keepOffline(track, "/api/stream/abc123")).toEqual({
      ok: false,
      reason: "this browser cannot keep music offline",
    });
    expect(await isKeptOffline(track)).toBe(false);
    expect(await forgetOffline(track)).toBe(false);
    expect(await keptCount()).toBe(0);
  });
});

describe("reading it back", () => {
  it("knows what is kept, and forgets on request", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("x", { status: 200 })));
    expect(await isKeptOffline(track)).toBe(false);
    await keepOffline(track, "/api/stream/abc123");
    expect(await isKeptOffline(track)).toBe(true);
    expect(await forgetOffline(track)).toBe(true);
    expect(await isKeptOffline(track)).toBe(false);
  });

  it("counts only the songs it owns", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("x", { status: 200 })));
    await keepOffline({ id: "one" }, "/api/stream/one");
    await keepOffline({ id: "two" }, "/api/stream/two");
    cache.store.set(`${window.location.origin}/app/static/thing.js`, new Response("js"));
    expect(await keptCount()).toBe(2);
  });

  it("clears the whole cache", async () => {
    const deleteSpy = vi.fn(async () => true);
    vi.stubGlobal("caches", { open: vi.fn(async () => cache), delete: deleteSpy });
    await clearOffline();
    expect(deleteSpy).toHaveBeenCalledWith("vyron-offline-v1");
  });

  it("survives a cache that throws", async () => {
    vi.stubGlobal("caches", {
      open: vi.fn(async () => ({
        match: vi.fn(async () => {
          throw new Error("denied");
        }),
        delete: vi.fn(async () => {
          throw new Error("denied");
        }),
        keys: vi.fn(async () => {
          throw new Error("denied");
        }),
      })),
    });
    expect(await isKeptOffline(track)).toBe(false);
    expect(await forgetOffline(track)).toBe(false);
    expect(await keptCount()).toBe(0);
    await expect(clearOffline()).resolves.toBeUndefined();
  });
});
