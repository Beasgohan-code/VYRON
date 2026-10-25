/**
 * The cover that flies — a shared-element transition, when the browser has one.
 *
 * Opening the player used to be two separate pictures: the dock's little square
 * vanished and a big one appeared. The View Transitions API lets the *same*
 * artwork travel between the two, which is the single strongest "this is an
 * app, not a page" cue on a phone.
 *
 * Everything is feature-detected and opt-in per call, so:
 *   · browsers without the API (older Telegram webviews) get the old instant
 *     swap — no error, no missing content;
 *   · `prefers-reduced-motion` keeps the swap;
 *   · a transition that is interrupted cannot leave the document stuck in the
 *     intermediate state, because the class is removed in `finished.finally`.
 */

const SUPPORTED = (): boolean => {
  if (typeof document === "undefined") return false;
  return typeof (document as Document & { startViewTransition?: unknown }).startViewTransition === "function";
};

function reduced(): boolean {
  try {
    return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
  } catch {
    return false;
  }
}

export type MorphDirection = "open" | "close";

/**
 * Run `change` inside a shared-element transition of the now-playing cover.
 *
 * `direction` decides *which* of the two covers takes part: naming both at once
 * is invalid, and the browser would drop the whole transition.
 */
export function morphCover(direction: MorphDirection, change: () => void): void {
  const doc = document as Document & { startViewTransition?: (cb: () => void) => { finished: Promise<void> } };
  const root = document.documentElement;
  if (!SUPPORTED() || reduced() || typeof doc.startViewTransition !== "function") {
    change();
    return;
  }
  let ran = false;
  const wrapped = () => {
    ran = true;
    change();
  };
  root.setAttribute("data-morph", direction);
  try {
    const transition = doc.startViewTransition(wrapped);
    void transition.finished.finally(() => root.removeAttribute("data-morph"));
  } catch {
    root.removeAttribute("data-morph");
    if (!ran) change();
  }
}
