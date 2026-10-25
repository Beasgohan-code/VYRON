/**
 * Artwork theming — the room takes the colour of the song.
 *
 * Every cover in the app is already drawn from a deterministic hash of the
 * track id (see `Cover.tsx`), so the same hash can tint the *interface* around
 * it: the dock's glow, the full player's ambience and its backdrop all follow
 * the artwork instead of sitting on one fixed accent. It is the difference
 * between "a dark app with a purple button" and an app that feels like it is
 * playing *this* song.
 *
 * The hues are written as CSS custom properties on <html>, so nothing has to
 * re-render when a track changes: the browser repaints the gradients. When
 * there is no track the app falls back to its own accent.
 */
import { useEffect } from "react";
import { hashOf } from "./format";

export interface Tint {
  /** Primary artwork hue, 0–359. */
  hue: number;
  /** Its warmer neighbour. */
  hue2: number;
  /** A contrasting third hue for highlights. */
  hue3: number;
}

/** The same three hues `Cover` uses, so picture and interface agree. */
export function tintFor(seedSource: string | number | null | undefined): Tint {
  const seed = hashOf(String(seedSource ?? "vyron"));
  const hue = seed % 360;
  return {
    hue,
    hue2: (hue + 48 + (seed % 60)) % 360,
    hue3: (hue + 168) % 360,
  };
}

function apply(tint: Tint | null): void {
  const root = document.documentElement;
  if (!tint) {
    root.style.removeProperty("--art-hue");
    root.style.removeProperty("--art-hue-2");
    root.style.removeProperty("--art-hue-3");
    root.removeAttribute("data-tinted");
    return;
  }
  root.style.setProperty("--art-hue", String(tint.hue));
  root.style.setProperty("--art-hue-2", String(tint.hue2));
  root.style.setProperty("--art-hue-3", String(tint.hue3));
  root.setAttribute("data-tinted", "");
}

/**
 * Follow the playing track. Call once, high in the tree.
 *
 * Cheap on purpose: one hash and three property writes per track, and the
 * gradients that read them are already painted.
 */
export function useArtworkTint(track: { id?: string | number; title?: string } | null): Tint | null {
  const tint = track ? tintFor(track.id ?? track.title ?? "") : null;
  const key = tint ? `${tint.hue}:${tint.hue2}` : "";
  useEffect(() => {
    apply(tint);
    return () => apply(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return tint;
}
