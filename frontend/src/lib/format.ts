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

export function compact(value: number | undefined): string {
  const num = Number(value) || 0;
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}k`;
  return String(num);
}
