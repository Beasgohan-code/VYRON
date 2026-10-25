import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
// Raw text, so the worker is executed exactly as the browser will run it.
import source from "../../public/sw.js?raw";

/**
 * The service worker is the one file that cannot be type-checked, so it is
 * exercised here for the part that is easy to get wrong: serving a *kept* song
 * to an audio element that asks for a byte range, offline.
 */
const ORIGIN = "https://app.test";

type Listener = (event: unknown) => void;
let listeners: Record<string, Listener>;
let store: Map<string, Response>;

function boot() {
  listeners = {};
  store = new Map();
  const self = {
    addEventListener: (name: string, fn: Listener) => {
      listeners[name] = fn;
    },
    location: { origin: ORIGIN },
    skipWaiting: vi.fn(),
    clients: { claim: vi.fn(async () => undefined) },
  };
  // eslint-disable-next-line no-new-func
  new Function("self", source)(self);
  vi.stubGlobal("caches", {
    open: vi.fn(async () => ({
      match: async (key: string) => store.get(key),
      put: async (key: string, value: Response) => void store.set(key, value),
      keys: async () => [],
    })),
    match: async () => undefined,
    delete: async () => true,
    keys: async () => [],
  });
}

/** Fire a fetch event and return the response the worker promised. */
async function dispatch(request: Request): Promise<Response | undefined> {
  let promised: Promise<Response> | undefined;
  listeners.fetch({ request, respondWith: (value: Promise<Response>) => (promised = value) });
  return promised ? await promised : undefined;
}

beforeEach(boot);
afterEach(() => vi.unstubAllGlobals());

describe("service worker offline audio", () => {
  const key = `${ORIGIN}/api/stream/track1`;

  function keep(payload: string) {
    store.set(key, new Response(payload, { status: 200, headers: { "content-type": "audio/mpeg" } }));
  }

  it("serves the whole stored song when the network is gone", async () => {
    keep("0123456789");
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new Error("offline"))));
    const response = await dispatch(
      new Request(`${ORIGIN}/api/stream/track1?t=secret`, { headers: { Range: "bytes=0-" } })
    );
    expect(response?.status).toBe(206);
    expect(await response?.text()).toBe("0123456789");
    expect(response?.headers.get("content-range")).toBe("bytes 0-9/10");
  });

  it("slices the middle of the file for a seek", async () => {
    keep("0123456789");
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new Error("offline"))));
    const response = await dispatch(
      new Request(`${ORIGIN}/api/stream/track1`, { headers: { Range: "bytes=2-4" } })
    );
    expect(response?.status).toBe(206);
    expect(await response?.text()).toBe("234");
    expect(response?.headers.get("content-range")).toBe("bytes 2-4/10");
    expect(response?.headers.get("content-length")).toBe("3");
    expect(response?.headers.get("accept-ranges")).toBe("bytes");
  });

  it("answers a suffix range from the end", async () => {
    keep("0123456789");
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new Error("offline"))));
    const response = await dispatch(
      new Request(`${ORIGIN}/api/stream/track1`, { headers: { Range: "bytes=-3" } })
    );
    expect(await response?.text()).toBe("789");
    expect(response?.headers.get("content-range")).toBe("bytes 7-9/10");
  });

  it("gives 416 past the end instead of a corrupt file", async () => {
    keep("0123456789");
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new Error("offline"))));
    const response = await dispatch(
      new Request(`${ORIGIN}/api/stream/track1`, { headers: { Range: "bytes=40-" } })
    );
    expect(response?.status).toBe(416);
    expect(response?.headers.get("content-range")).toBe("bytes */10");
  });

  it("prefers the network when it is there — no stale song", async () => {
    keep("stored");
    const fetched = new Response("fresh", { status: 200 });
    vi.stubGlobal("fetch", vi.fn(async () => fetched));
    const response = await dispatch(new Request(`${ORIGIN}/api/stream/track1`));
    expect(await response?.text()).toBe("fresh");
  });

  it("fails loudly when nothing is kept", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new Error("offline"))));
    await expect(dispatch(new Request(`${ORIGIN}/api/stream/unknown`))).rejects.toThrow("offline");
  });

  it("still never touches the rest of the API", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
    let promised: Promise<Response> | undefined;
    listeners.fetch({
      request: new Request(`${ORIGIN}/api/state`),
      respondWith: (value: Promise<Response>) => (promised = value),
    });
    expect(promised).toBeUndefined();
  });
});
