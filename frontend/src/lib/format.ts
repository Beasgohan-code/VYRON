/** Seconds → `m:ss` (or `h:mm:ss`). */
export function fmtDuration(seconds: number | undefined | null): string {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return hours ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${minutes}:${pad(secs)}`;
}

export function totalDuration(tracks: { duration?: number }[] | undefined): string {
  return fmtDuration((tracks ?? []).reduce((sum, track) => sum + (Number(track.duration) || 0), 0));
}

export function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 5) return "Good night,";
  if (hour < 12) return "Good morning,";
  if (hour < 17) return "Good afternoon,";
  if (hour < 22) return "Good evening,";
  return "Good night,";
}

/** Stable hash so a track always maps to the same fallback cover. */
export function hashOf(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) | 0;
  }
  return Math.abs(hash);
}

/**
 * Real artwork only. When a track has no thumbnail the UI draws its own
 * (see `Cover`), so there is no placeholder folder to ship or keep in sync.
 */
export function thumbFor(track?: { thumbnail?: string | null } | null): string | null {
  return track?.thumbnail || null;
}

export function initials(name: string | undefined): string {
  const clean = (name ?? "").trim();
  if (!clean) return "V";
  const parts = clean.split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase() ?? "").join("") || "V";
}

/** Bytes → `1.4 GB`, for quota volume. */
export function fmtBytes(bytes: number | undefined | null): string {
  const value = Math.max(0, Number(bytes) || 0);
  if (value < 1024) return `${value} B`;
  const units = ["kB", "MB", "GB", "TB"];
  let size = value / 1024;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size >= 10 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
}

export function compact(value: number | undefined): string {
  const num = Number(value) || 0;
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}k`;
  return String(num);
}

/**
 * Which lyric line is playing right now (`-1` before the first one).
 *
 * A small lead-in is deliberate: highlighting a line a beat early reads better
 * than a line that lights up after it has already been sung.
 */
export function activeLyricLine(
  lines: { time: number; text?: string }[] | undefined,
  position: number,
  lead = 0.4
): number {
  if (!lines?.length) return -1;
  let active = -1;
  for (let index = 0; index < lines.length; index += 1) {
    if (lines[index].time <= position + lead) active = index;
    else break;
  }
  return active;
}

/* ── artwork ──────────────────────────────────────────────────────────────── */

const YTIMG = /^https?:\/\/i\d?\.ytimg\.com\/vi(?:_webp)?\/([A-Za-z0-9_-]{6,})\/([a-z]+)\.(jpg|webp)$/i;

/**
 * Ask YouTube for the biggest version of the same image.
 *
 * Search results come back with a 120×90 `default.jpg`, which is a blurry mess
 * behind a 320 px player and a genuinely bad lock-screen cover. The video id is
 * in the URL, so the high-resolution file is the same URL with a different
 * filename — no extra request, no extra API.
 *
 * Non-YouTube URLs (and already-large ones) are returned untouched.
 */
export function artworkHiRes(url?: string | null): string | null {
  if (!url) return null;
  const match = YTIMG.exec(url);
  if (!match) return url;
  const [, id, size] = match;
  if (["maxresdefault", "sddefault", "hqdefault"].includes(size.toLowerCase())) return url;
  return `https://i.ytimg.com/vi/${id}/maxresdefault.jpg`;
}
