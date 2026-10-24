/**
 * Keyboard shortcuts, as data.
 *
 * A phone-first app still gets opened on a desktop (Telegram Web, or a browser
 * tab), and on a desktop every music player answers the space bar. The mapping
 * lives here as a table so the overlay can be generated from it and the tests
 * can prove what each key does — including what it deliberately does *not* do
 * while you are typing in the search box.
 */
export type ShortcutId =
  | "toggle"
  | "next"
  | "prev"
  | "seekForward"
  | "seekBack"
  | "volumeUp"
  | "volumeDown"
  | "mute"
  | "search"
  | "help"
  | "escape"
  | "queue"
  | "like";

export interface KeyLike {
  key: string;
  code?: string;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
}

export interface Shortcut {
  id: ShortcutId;
  /** Human label for the overlay. */
  label: string;
  /** Keys as printed in the overlay. */
  keys: string[];
}

export const SHORTCUTS: Shortcut[] = [
  { id: "toggle", label: "Play / pause", keys: ["Space"] },
  { id: "next", label: "Next track", keys: ["N", "⇧ →"] },
  { id: "prev", label: "Previous track", keys: ["P", "⇧ ←"] },
  { id: "seekForward", label: "Forward 10s", keys: ["→"] },
  { id: "seekBack", label: "Back 10s", keys: ["←"] },
  { id: "volumeUp", label: "Louder", keys: ["↑"] },
  { id: "volumeDown", label: "Quieter", keys: ["↓"] },
  { id: "mute", label: "Mute", keys: ["M"] },
  { id: "like", label: "Like this track", keys: ["L"] },
  { id: "search", label: "Search", keys: ["/"] },
  { id: "queue", label: "Queue", keys: ["Q"] },
  { id: "help", label: "This list", keys: ["?"] },
  { id: "escape", label: "Close / back", keys: ["Esc"] },
];

/** True when a keystroke belongs to a text field rather than to us. */
export function isTyping(target: EventTarget | null): boolean {
  if (!target || typeof (target as HTMLElement).tagName !== "string") return false;
  const element = target as HTMLElement;
  const tag = element.tagName.toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return element.isContentEditable === true;
}

/**
 * Map a keystroke to an action, or `null` when it is not ours.
 *
 * `focus` is the element that has focus; typing into a field swallows
 * everything except Escape, so space types a space instead of pausing the song.
 */
export function shortcutFor(event: KeyLike, focus: EventTarget | null = null): ShortcutId | null {
  const typing = isTyping(focus);
  const key = event.key;

  if (key === "Escape") return "escape";
  if (typing) return null;
  // Let the browser and the OS keep their own chords (⌘K, Ctrl+L, …).
  if (event.metaKey || event.ctrlKey || event.altKey) return null;

  switch (key) {
    case " ":
    case "Spacebar":
      return "toggle";
    case "ArrowRight":
      return event.shiftKey ? "next" : "seekForward";
    case "ArrowLeft":
      return event.shiftKey ? "prev" : "seekBack";
    case "ArrowUp":
      return "volumeUp";
    case "ArrowDown":
      return "volumeDown";
    case "?":
      return "help";
    case "/":
      return "search";
    case "q":
    case "Q":
      return "queue";
    case "n":
    case "N":
      return "next";
    case "p":
    case "P":
      return "prev";
    case "m":
    case "M":
      return "mute";
    case "l":
    case "L":
      return "like";
    default:
      return null;
  }
}

export const SEEK_STEP = 10;
export const VOLUME_STEP = 0.05;
