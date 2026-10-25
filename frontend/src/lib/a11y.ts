/**
 * Focus, for the things that float above the app.
 *
 * A `<div role="dialog" aria-modal="true">` is a promise: the rest of the page
 * is not reachable while it is open. Without moving focus into it, the promise
 * is false — a keyboard tabs into the queue behind the player, and a screen
 * reader keeps reading the page underneath. This hook keeps the promise:
 *
 *   1. remember what had focus;
 *   2. move focus inside (the container, or the first control);
 *   3. keep Tab inside while it is open;
 *   4. put focus back where it came from on close.
 *
 * It is deliberately small: no portal, no library, no global key handler — the
 * dialogs already own their own Escape.
 */
import { useEffect, useRef } from "react";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/**
 * Is this node actually reachable?
 *
 * `offsetParent === null` is the usual trick and it is wrong here: an element
 * inside a `position: fixed` dialog has no offset parent even when it is
 * perfectly visible, so that test would empty the trap in the one place it is
 * used. Computed style is what "visible" means to a browser, and unlike
 * `getClientRects()` it also works in jsdom, where every box is zero-sized.
 */
function visible(node: HTMLElement): boolean {
  if (node.hasAttribute("hidden") || node.getAttribute("aria-hidden") === "true") return false;
  if (node.closest("[inert]")) return false;
  const style = window.getComputedStyle(node);
  return style.display !== "none" && style.visibility !== "hidden" && style.visibility !== "collapse";
}

function focusable(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(visible);
}

/**
 * Keep focus inside *ref* while *active* is true.
 *
 * The container itself is made focusable (`tabIndex={-1}` is set for you) so a
 * dialog with no controls still takes focus instead of leaving it outside.
 */
export function useFocusTrap(ref: React.RefObject<HTMLElement>, active: boolean): void {
  const restoreTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!active) return undefined;
    const root = ref.current;
    if (!root) return undefined;

    restoreTo.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    root.setAttribute("tabindex", "-1");
    // First control if there is one (the close button), else the dialog itself —
    // focusing the container reads the dialog's label, which is the useful thing.
    const [first] = focusable(root);
    (first ?? root).focus({ preventScroll: true });

    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const nodes = focusable(root);
      if (!nodes.length) {
        event.preventDefault();
        root.focus({ preventScroll: true });
        return;
      }
      const head = nodes[0];
      const tail = nodes[nodes.length - 1];
      const current = document.activeElement;
      if (event.shiftKey && (current === head || current === root)) {
        event.preventDefault();
        tail.focus();
      } else if (!event.shiftKey && current === tail) {
        event.preventDefault();
        head.focus();
      }
    };

    root.addEventListener("keydown", onKey);
    return () => {
      root.removeEventListener("keydown", onKey);
      const back = restoreTo.current;
      if (back && document.contains(back)) back.focus({ preventScroll: true });
    };
  }, [ref, active]);
}

/**
 * Announce a short sentence to assistive tech without a visible change.
 *
 * React re-renders the same string constantly (the player ticks four times a
 * second); `aria-live` only speaks when the *text* changes, which is what this
 * hook guarantees by keying on the value itself.
 */
export function useAnnouncer(message: string): React.ReactNode {
  return message;
}
