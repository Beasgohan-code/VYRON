/**
 * One shared three.js loader.
 *
 * three.js is ~465 kB of the bundle and exists only for decoration, so it must
 * never be part of the first paint. Two rules live here:
 *
 *   1. import it once — every visual asks the same promise, so a second mount
 *      (the dock coming up while the player is open) costs nothing;
 *   2. do not import it at all on a connection that cannot afford it. Save-Data
 *      and 2G mean "skip the backdrop", not "download half a megabyte and tell
 *      the user nothing".
 */
import type * as Three from "./three-runtime";

type ThreeModule = typeof Three;

let pending: Promise<ThreeModule> | null = null;

interface NetworkInformation {
  saveData?: boolean;
  effectiveType?: string;
}

function connection(): NetworkInformation | undefined {
  return (navigator as unknown as { connection?: NetworkInformation }).connection;
}

/** False on a metered or very slow connection, where the scene is not worth it. */
export function visualsWorthLoading(): boolean {
  const net = connection();
  if (!net) return true;
  if (net.saveData) return false;
  return net.effectiveType !== "slow-2g" && net.effectiveType !== "2g";
}

/** The three.js module, downloaded at most once per session. */
export function loadThree(): Promise<ThreeModule> {
  pending ??= import("./three-runtime");
  return pending;
}

/** Test seam: forget the cached import (and allow a different network). */
export function resetThreeLoader(): void {
  pending = null;
}

/**
 * Run `work` when the browser is idle — after the shell has painted, before the
 * user notices a missing backdrop.
 */
export function whenIdle(work: () => void, timeout = 1200): () => void {
  const idle = (window as unknown as { requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number })
    .requestIdleCallback;
  if (typeof idle === "function") {
    let cancelled = false;
    const cancelIdle = (window as unknown as { cancelIdleCallback?: (handle: number) => void })
      .cancelIdleCallback;
    const handle = idle(() => {
      if (!cancelled) work();
    }, { timeout });
    return () => {
      cancelled = true;
      cancelIdle?.(handle);
    };
  }
  const timer = window.setTimeout(work, 180);
  return () => window.clearTimeout(timer);
}
