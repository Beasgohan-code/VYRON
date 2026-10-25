/**
 * The Telegram client, in one place.
 *
 * A Mini App is not a web page that happens to be inside Telegram — it lives
 * inside a client that owns the back gesture, the colours, the viewport, the
 * closing behaviour and the haptics. This module is the only code that talks to
 * `window.Telegram`, so every screen gets the same behaviour and every call is
 * guarded: in a plain browser (or an old client) each feature is simply absent
 * instead of throwing.
 */
import { useEffect, useRef } from "react";

export type HapticStyle = "light" | "medium" | "heavy" | "rigid" | "soft";
export type HapticNotice = "error" | "success" | "warning";

export interface ThemeParams {
  bg_color?: string;
  secondary_bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  header_bg_color?: string;
  accent_text_color?: string;
  section_bg_color?: string;
  section_header_text_color?: string;
  subtitle_text_color?: string;
  destructive_text_color?: string;
}

interface BackButton {
  show?: () => void;
  hide?: () => void;
  onClick?: (handler: () => void) => void;
  offClick?: (handler: () => void) => void;
  isVisible?: boolean;
}

interface WebApp {
  initData?: string;
  initDataUnsafe?: { start_param?: string; user?: { id?: number } };
  colorScheme?: "light" | "dark";
  themeParams?: ThemeParams;
  viewportHeight?: number;
  viewportStableHeight?: number;
  isExpanded?: boolean;
  platform?: string;
  ready?: () => void;
  expand?: () => void;
  close?: () => void;
  requestFullscreen?: () => void;
  exitFullscreen?: () => void;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
  setBottomBarColor?: (color: string) => void;
  enableClosingConfirmation?: () => void;
  disableClosingConfirmation?: () => void;
  disableVerticalSwipes?: () => void;
  enableVerticalSwipes?: () => void;
  openTelegramLink?: (url: string) => void;
  openLink?: (url: string, options?: { try_instant_view?: boolean }) => void;
  shareToStory?: (media: string, params?: Record<string, unknown>) => void;
  onEvent?: (event: string, handler: () => void) => void;
  offEvent?: (event: string, handler: () => void) => void;
  BackButton?: BackButton;
  HapticFeedback?: {
    impactOccurred?: (style: HapticStyle) => void;
    notificationOccurred?: (type: HapticNotice) => void;
    selectionChanged?: () => void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp?: WebApp };
  }
}

export const webApp = (): WebApp | undefined => window.Telegram?.WebApp;
/** Back-compat alias: half the app says `telegram()`, the newer code says `webApp()`. */
export const telegram = webApp;

/** True when we are inside a Telegram client with the SDK loaded. */
export function insideTelegram(): boolean {
  return Boolean(webApp()?.initData);
}

const call = <T>(fn: (() => T) | undefined): T | undefined => {
  try {
    return fn?.();
  } catch {
    return undefined; // an older client without this method must not crash us
  }
};

/* ── boot ──────────────────────────────────────────────────────────────── */
/**
 * Tell the client we are ready and take the whole screen.
 *
 * `ready()` is what stops Telegram showing its own spinner over our boot
 * screen. Both calls are no-ops outside Telegram.
 */
export function bootClient(): void {
  const app = webApp();
  if (!app) return;
  call(() => app.ready?.());
  call(() => app.expand?.());
}

/* ── colours ───────────────────────────────────────────────────────────── */
/**
 * Push our surface colours into the client's chrome.
 *
 * String aliases (`bg_color`, `secondary_bg_color`) are supported by current
 * clients and survive a theme switch; older ones need a literal hex, which we
 * take from the params the client handed us.
 */
export function paintChrome(): void {
  const app = webApp();
  if (!app) return;
  const params = app.themeParams ?? {};
  const bg = params.bg_color || "#08080e";
  const secondary = params.secondary_bg_color || bg;
  for (const method of ["setHeaderColor", "setBackgroundColor"] as const) {
    const fn = app[method];
    if (!fn) continue;
    try {
      fn("bg_color");
    } catch {
      try {
        fn(bg);
      } catch {
        /* nothing else to try */
      }
    }
  }
  try {
    app.setBottomBarColor?.(secondary);
  } catch {
    /* Bot API < 7.10 */
  }
}

/**
 * Mirror the client's colour scheme onto `<html>`.
 *
 * The CSS does the colour work from Telegram's own `--tg-theme-*` variables;
 * what it cannot know is *which* scheme is active and whether the user chose
 * "Telegram" as their theme at all — that is what these attributes carry.
 */
export function syncScheme(): { scheme: "light" | "dark" } {
  const app = webApp();
  const scheme = app?.colorScheme === "light" ? "light" : "dark";
  const root = document.documentElement;
  root.dataset.scheme = scheme;
  // The client injects fresh `--tg-theme-*` values before firing themeChanged;
  // re-reading them is what makes a switch instant instead of needing a reload.
  const params = app?.themeParams ?? {};
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "string" && value) root.style.setProperty(`--tg-${key.replace(/_/g, "-")}`, value);
  }
  return { scheme };
}

/* ── viewport (and the keyboard) ───────────────────────────────────────── */
interface Viewport {
  height: number;
  stable: number;
  keyboard: number;
}

/** Current viewport in CSS-friendly numbers. */
export function viewport(): Viewport {
  const app = webApp();
  const stable = Number(app?.viewportStableHeight) || window.innerHeight;
  const height = Number(app?.viewportHeight) || window.innerHeight;
  return { height, stable, keyboard: Math.max(0, stable - height) };
}

/**
 * Publish the viewport as CSS variables.
 *
 * Two things depend on it: the shell must be exactly as tall as the visible
 * area (Telegram's webview does not honour `100dvh` on every platform), and
 * when the keyboard opens the dock must get out of its way instead of sitting
 * on top of the input. A 120 px threshold keeps browser chrome (which also
 * shrinks the viewport) from being mistaken for a keyboard.
 */
export function applyViewport(): Viewport {
  const size = viewport();
  const root = document.documentElement;
  root.style.setProperty("--tg-vh", `${size.height}px`);
  root.style.setProperty("--tg-stable-vh", `${size.stable}px`);
  root.style.setProperty("--tg-keyboard", `${size.keyboard}px`);
  root.dataset.keyboard = size.keyboard > 120 ? "open" : "closed";
  return size;
}

/* ── back button ───────────────────────────────────────────────────────── */
/** Show the client's back arrow and route it. Returns a cleanup. */
export function bindBack(active: boolean, onBack: () => void): () => void {
  const button = webApp()?.BackButton;
  if (!button) return () => undefined;
  if (!active) {
    call(() => button.hide?.());
    return () => undefined;
  }
  call(() => button.onClick?.(onBack));
  call(() => button.show?.());
  return () => {
    call(() => button.offClick?.(onBack));
    call(() => button.hide?.());
  };
}

/**
 * A declarative back button.
 *
 * `onBack` is kept in a ref so a re-render does not re-register the handler on
 * every tick of the clock — the client keeps the *first* handler it was given
 * until it is removed, and a stale closure there is how "back" stops working.
 */
export function useBackButton(active: boolean, onBack: () => void): void {
  const latest = useRef(onBack);
  latest.current = onBack;
  useEffect(() => {
    if (!active) {
      call(() => webApp()?.BackButton?.hide?.());
      return undefined;
    }
    const handler = () => latest.current();
    const button = webApp()?.BackButton;
    call(() => button?.onClick?.(handler));
    call(() => button?.show?.());
    return () => {
      call(() => button?.offClick?.(handler));
      call(() => button?.hide?.());
    };
  }, [active]);
}

/* ── closing & swipes ──────────────────────────────────────────────────── */
/**
 * Ask before the user swipes the Mini App away — but only while it matters.
 *
 * A closed Mini App is a stopped song, and Telegram's close affordance is one
 * drag away. Turning the guard on only while audio plays keeps the normal
 * "get me out of here" flow quick.
 */
export function guardClose(on: boolean): void {
  const app = webApp();
  if (!app) return;
  try {
    if (on) app.enableClosingConfirmation?.();
    else app.disableClosingConfirmation?.();
  } catch {
    /* older clients */
  }
}

/**
 * Stop Telegram's own vertical-swipe gesture from fighting ours.
 *
 * In the full-screen player a vertical drag is "pull the sheet down"; with the
 * client's gesture enabled the same drag closes the app instead.
 */
export function lockSwipes(on: boolean): void {
  const app = webApp();
  if (!app) return;
  try {
    if (on) app.disableVerticalSwipes?.();
    else app.enableVerticalSwipes?.();
  } catch {
    /* Bot API < 7.7 */
  }
}

/* ── deep links ────────────────────────────────────────────────────────── */
export type StartTarget =
  | { kind: "playlist"; id: string }
  | { kind: "mix"; key: string }
  | { kind: "search"; query: string }
  | { kind: "view"; view: string };

/**
 * Read `?startapp=` (the `t.me/<bot>?startapp=…` menu link).
 *
 * The parameter is a *hint from the user*, so every value is trimmed and
 * length-limited before it reaches a request; anything unrecognised is ignored
 * rather than guessed at.
 */
export function startTarget(raw = webApp()?.initDataUnsafe?.start_param ?? ""): StartTarget | null {
  const value = String(raw ?? "").trim().slice(0, 200);
  if (!value) return null;
  const [kind, ...rest] = value.split(/[_-]/);
  const tail = rest.join("-").trim();
  if (!tail) {
    const simple = value.toLowerCase();
    return ["home", "search", "library", "rooms", "profile", "api"].includes(simple)
      ? { kind: "view", view: simple }
      : null;
  }
  switch (kind.toLowerCase()) {
    case "playlist":
      return { kind: "playlist", id: tail };
    case "mix":
      return { kind: "mix", key: tail };
    case "search":
      return { kind: "search", query: tail.replace(/\s+/g, " ") };
    default:
      return null;
  }
}

/* ── haptics ───────────────────────────────────────────────────────────── */
export function haptic(style: HapticStyle = "light"): void {
  try {
    webApp()?.HapticFeedback?.impactOccurred?.(style);
  } catch {
    /* Telegram may not expose haptics on every platform */
  }
}

export function notify(type: HapticNotice): void {
  try {
    webApp()?.HapticFeedback?.notificationOccurred?.(type);
  } catch {
    /* ignore */
  }
}

export function selection(): void {
  try {
    webApp()?.HapticFeedback?.selectionChanged?.();
  } catch {
    /* ignore */
  }
}

/* ── sharing ───────────────────────────────────────────────────────────── */
/**
 * Hand a link to the client's own share sheet.
 *
 * `openTelegramLink` keeps the user inside Telegram (the chat picker), which is
 * where a music link belongs; the browser is the fallback.
 */
export function shareLink(url: string, text = ""): void {
  const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(url)}${
    text ? `&text=${encodeURIComponent(text)}` : ""
  }`;
  const app = webApp();
  if (app?.openTelegramLink) {
    call(() => app.openTelegramLink?.(shareUrl));
    return;
  }
  try {
    window.open(shareUrl, "_blank", "noopener,noreferrer");
  } catch {
    /* pop-up blocked; nothing else to try */
  }
}

export async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    // Older webviews have no async clipboard; a hidden textarea still works.
    try {
      const area = document.createElement("textarea");
      area.value = value;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const copied = document.execCommand("copy");
      area.remove();
      return copied;
    } catch {
      return false;
    }
  }
}

/* ── the one listener ──────────────────────────────────────────────────── */
/**
 * Subscribe to the client's theme and viewport events.
 *
 * Telegram fires `themeChanged` *before* the new `themeParams` are readable in
 * some clients and after in others, so the handler re-syncs on both the event
 * and the next frame. Cheap, and it removes a class of "half-updated theme".
 */
export function watchClient(handlers: { onChange?: () => void } = {}): () => void {
  const app = webApp();
  if (!app?.onEvent) return () => undefined;
  const run = () => {
    syncScheme();
    paintChrome();
    applyViewport();
    handlers.onChange?.();
    window.requestAnimationFrame(() => {
      syncScheme();
      applyViewport();
    });
  };
  const events = ["themeChanged", "viewportChanged", "safeAreaChanged", "contentSafeAreaChanged"];
  for (const event of events) call(() => app.onEvent?.(event, run));
  // Browsers (and the PWA on Android) also move the visual viewport when the
  // keyboard appears; Telegrams's `viewportChanged` is not fired there.
  const visual = window.visualViewport;
  const onResize = () => applyViewport();
  visual?.addEventListener?.("resize", onResize);
  window.addEventListener("resize", onResize);
  return () => {
    for (const event of events) call(() => app.offEvent?.(event, run));
    visual?.removeEventListener?.("resize", onResize);
    window.removeEventListener("resize", onResize);
  };
}

/** Everything a first paint needs, in one call. */
export function bootShell(): void {
  bootClient();
  syncScheme();
  paintChrome();
  applyViewport();
}
