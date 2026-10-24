/**
 * Mini App as an app: service worker registration and connection state.
 *
 * Two separate concerns live here on purpose — `registerApp()` decides whether a
 * service worker is safe to install at all, and `useConnection()` tells the UI
 * when the network has gone away so it can say "offline" honestly instead of
 * leaving a spinner forever.
 */
import { useEffect, useState } from "react";

const SW_URL = "/app/sw.js";
const SW_SCOPE = "/app/";

/** True when a service worker may be installed in this context. */
export function canRegister(): boolean {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return false;
  if (typeof window === "undefined" || !window.isSecureContext) return false;
  // A dev server has no built shell to cache and no stable asset names.
  return import.meta.env.PROD;
}

/**
 * Install the offline shell. Returns an "update ready" callback so the UI can
 * offer a reload when a new build lands behind an open tab.
 */
export function registerApp(onUpdate?: () => void): void {
  if (!canRegister()) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register(SW_URL, { scope: SW_SCOPE })
      .then((registration) => {
        registration.addEventListener("updatefound", () => {
          const installing = registration.installing;
          if (!installing) return;
          installing.addEventListener("statechange", () => {
            // `controller` is null on the very first install: that is not an
            // update, it is simply the app becoming available offline.
            if (installing.state === "installed" && navigator.serviceWorker.controller) {
              onUpdate?.();
            }
          });
        });
      })
      .catch(() => {
        /* private mode, an old Telegram webview — the app works without it */
      });
  });
}

/** `navigator.onLine`, kept in React state. */
export function useConnection(): { online: boolean; since?: number } {
  const [online, setOnline] = useState(() =>
    typeof navigator === "undefined" ? true : navigator.onLine
  );
  const [since, setSince] = useState<number | undefined>(undefined);

  useEffect(() => {
    const goOnline = () => {
      setOnline(true);
      setSince(undefined);
    };
    const goOffline = () => {
      setOnline(false);
      setSince(Date.now());
    };
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  return { online, since };
}

/**
 * True once a newer build is waiting. The app shows a "reload" chip rather than
 * swapping the shell underneath a playing track.
 */
export function useUpdateReady(): { ready: boolean; reload: () => void } {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const onUpdate = () => setReady(true);
    window.addEventListener("vyron:update-ready", onUpdate);
    return () => window.removeEventListener("vyron:update-ready", onUpdate);
  }, []);

  const reload = () => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) {
      window.location.reload();
      return;
    }
    navigator.serviceWorker.getRegistration(SW_SCOPE).then((registration) => {
      registration?.waiting?.postMessage({ type: "SKIP_WAITING" });
      window.location.reload();
    });
  };

  return { ready, reload };
}
