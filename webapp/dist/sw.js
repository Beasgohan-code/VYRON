/*
 * VYRON Mini App — service worker.
 *
 * The shell is small and the assets are content-hashed, so this does two
 * things and nothing else:
 *
 *   navigation  network-first, cached shell as the fallback — opening the app
 *               on a dead connection lands you in the same UI, not a browser
 *               error page;
 *   assets      stale-while-revalidate — instant on the second visit, and a
 *               new deploy is picked up on the next one (filenames change).
 *
 * Anything that carries state (the API, the audio proxy, auth) is never cached:
 * a stale queue or a cached "who am I" is worse than a spinner.
 *
 * The one exception is the songs the listener chose to keep. Those live in a
 * separate, unversioned cache (`vyron-offline-v1`) that this worker never
 * writes to — `lib/offline.ts` fills it, one explicit request at a time — and
 * it is only read when the network has already failed. Range requests are
 * sliced out of the stored body, because a lone 200 answer would let the audio
 * element play but never seek.
 */
/* Bumped when the cached shell would otherwise keep serving an old picture:
   activate deletes every cache that does not carry this prefix. */
const VERSION = "vyron-3";
/* Written by the page, read here. Never deleted by `activate`: it is not shell. */
const OFFLINE = "vyron-offline-v1";
const SHELL = `${VERSION}-shell`;
const ASSETS = `${VERSION}-assets`;
const SHELL_FILES = [
  "/app/",
  "/app/static/manifest.webmanifest",
  "/app/static/brand/icon-192.png",
  "/app/static/brand/icon-512.png",
  "/app/static/brand/avatar.jpg",
  "/app/static/brand/boot.jpg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL)
      // One missing file must not fail the install; the shell is still cached.
      .then((cache) => Promise.allSettled(SHELL_FILES.map((file) => cache.add(file))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => !key.startsWith(VERSION)).map((key) => caches.delete(key)))
      )
      .then(() => self.clients.claim())
  );
});

/** Never cache the things a stale copy would lie about. */
function isDynamic(url) {
  return (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/v1/") ||
    url.pathname.startsWith("/audio/") ||
    url.pathname.startsWith("/auth") ||
    url.pathname.startsWith("/health") ||
    url.pathname.startsWith("/ready")
  );
}

/**
 * A stored song, served for the byte range the player asked for.
 *
 * `bytes=0-` and no Range header are the same thing; a range that starts past
 * the end is answered with 416 rather than a corrupt file.
 */
async function fromOffline(request, url) {
  const cache = await caches.open(OFFLINE);
  const cached = await cache.match(url.origin + url.pathname);
  if (!cached) return null;
  const header = request.headers.get("range");
  if (!header) return cached;

  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!match) return cached;
  const body = await cached.arrayBuffer();
  const size = body.byteLength;
  let start = match[1] === "" ? size - Number(match[2] || 0) : Number(match[1]);
  let end = match[1] === "" || match[2] === "" ? size - 1 : Number(match[2]);
  if (!Number.isFinite(start) || start < 0) start = 0;
  if (!Number.isFinite(end) || end >= size) end = size - 1;

  const type = cached.headers.get("content-type") || "audio/mpeg";
  if (start >= size) {
    return new Response(null, {
      status: 416,
      headers: { "Content-Range": `bytes */${size}`, "Accept-Ranges": "bytes" },
    });
  }
  return new Response(body.slice(start, end + 1), {
    status: 206,
    statusText: "Partial Content",
    headers: {
      "Content-Type": type,
      "Content-Range": `bytes ${start}-${end}/${size}`,
      "Content-Length": String(end - start + 1),
      "Accept-Ranges": "bytes",
    },
  });
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  let url;
  try {
    url = new URL(request.url);
  } catch {
    return;
  }

  // A kept song: the network first (it may be a fresher link), the stored copy
  // when that fails. Never cached on the way through — keeping is explicit.
  if (url.origin === self.location.origin && url.pathname.startsWith("/api/stream/")) {
    event.respondWith(
      fetch(request).catch(async (error) => {
        const offline = await fromOffline(request, url).catch(() => null);
        if (offline) return offline;
        throw error;
      })
    );
    return;
  }

  if (url.origin !== self.location.origin || isDynamic(url)) return;

  // The page itself: fresh when the network is there, cached shell when not.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(SHELL).then((cache) => cache.put("/app/", copy));
          }
          return response;
        })
        .catch(async () => {
          const cached = (await caches.match("/app/")) || (await caches.match("/app/static/index.html"));
          return (
            cached ||
            new Response(
              "<!doctype html><meta name=viewport content='width=device-width'><body style='background:#05070a;color:#eaf6f4;font:16px system-ui;display:grid;place-items:center;height:100vh;margin:0;text-align:center'><div><p style='font-size:20px;font-weight:700'>VYRON is offline</p><p style='opacity:.6'>Reconnect, then reopen the Mini App.</p></div>",
              { headers: { "Content-Type": "text/html; charset=utf-8" } }
            )
          );
        })
    );
    return;
  }

  if (!url.pathname.startsWith("/app/static/")) return;

  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(ASSETS).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
