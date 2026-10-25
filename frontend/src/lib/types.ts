export type View = "home" | "search" | "library" | "queue" | "playlists" | "rooms" | "api" | "profile";

export type LoopMode = "off" | "one" | "all";

export interface Track {
  id?: string;
  title: string;
  uploader?: string;
  duration?: number;
  thumbnail?: string | null;
  source?: string;
  url?: string;
  query?: string;
  index?: number;
  video?: boolean;
  requested_by?: string;
  views?: number;
}

export interface NowPlaying extends Track {
  elapsed: number;
  progress?: number;
  paused: boolean;
  volume?: number;
  loop?: LoopMode;
}

export interface Settings {
  volume: number;
  loop: LoopMode;
  autoplay: boolean;
  always_on: boolean;
  shuffle: boolean;
  effects: string[];
}

export interface Playlist {
  id: string;
  name: string;
  count: number;
  duration: number;
  covers?: string[];
  tracks?: Track[];
  created?: number;
}

export interface Room {
  chat_id: number;
  title: string;
  username?: string;
  listeners: number;
  playing: boolean;
  paused: boolean;
  track: Track | null;
  volume?: number;
  effects?: string[];
}

export type ApiScope = "read" | "search" | "download" | "admin";

export interface ApiKey {
  key?: string;
  masked?: string;
  preview?: string;
  id?: string;
  prefix?: string;
  label?: string;
  owner_id?: number;
  scopes?: ApiScope[];
  active?: boolean;
  uses?: number;
  bytes?: number;
  created_at?: number;
  last_used_at?: number | null;
  expires_at?: number | null;
  expired?: boolean;
  revoked_at?: number | null;
  rate_limit?: number | null;
  daily_requests?: number | null;
  monthly_requests?: number | null;
  daily_bytes?: number | null;
  monthly_bytes?: number | null;
  quota?: ApiQuota;
}

export interface ApiQuota {
  limits: Record<string, number>;
  used: {
    day: { key: string; requests: number; bytes: number };
    month: { key: string; requests: number; bytes: number };
  };
  remaining: Record<string, number | null>;
  exceeded: string[];
}

export interface ApiSource {
  name: string;
  label?: string;
  kind: "search" | "catalogue" | "stream" | string;
  enabled: boolean;
  available: boolean;
  failures?: number;
  detail?: string;
  last_ok?: number | null;
}

export interface ApiKeyUpdate {
  id: string;
  label?: string;
  scopes?: ApiScope[];
  days?: number | null;
  rate_limit?: number | null;
}

export interface ApiMetrics {
  requests: number;
  downloads: number;
  bytes_served: number;
  rate_limited: number;
  uptime_seconds: number;
  latency_ms: { avg: number; p50: number; p95: number; p99: number };
  by_status?: Record<string, number>;
}

export interface ApiKeyPayload {
  ok: boolean;
  preview?: boolean;
  base: string;
  docs: string;
  is_owner: boolean;
  openapi?: string;
  keys: ApiKey[];
  scopes?: ApiScope[];
  default_scopes?: ApiScope[];
  version?: string;
  metrics?: ApiMetrics;
  stats: {
    enabled: boolean;
    open: boolean;
    keys: number;
    keys_total?: number;
    requests: number;
    bytes: number;
    rate_limit: number;
    storage: string;
    version?: string;
  };
  created?: ApiKey;
  revoked?: boolean;
  updated?: boolean;
  sources?: ApiSource[];
  source_order?: string;
  limits?: { max_keys: number };
}

export interface ApiKeyOptions {
  label?: string;
  scopes?: ApiScope[];
  days?: number | null;
  rate_limit?: number | null;
  daily_requests?: number | null;
  monthly_requests?: number | null;
  daily_bytes?: number | null;
  monthly_bytes?: number | null;
}

export interface ApiHealth {
  status: string;
  streaming?: boolean;
  ok: boolean;
  service: string;
  version: string;
  uptime: number;
  ready: boolean;
  auth_required: boolean;
  rate_limit: number;
  keys: number;
  endpoints: string[];
}

export interface LanguageOption {
  code: string;
  /** The language's own name — "മലയാളം", never "Malayalam". */
  name: string;
  rtl?: boolean;
}

export interface LanguageState {
  code: string;
  name: string;
  rtl?: boolean;
  available: LanguageOption[];
}

export interface AppState {
  ok: boolean;
  preview?: boolean;
  version?: string;
  bot?: string;
  streaming?: boolean;
  user?: {
    id?: number;
    name?: string;
    username?: string;
    owner?: boolean;
    access?: string;
    /** Signed Telegram picture URL — a cache seed, not something we render. */
    photo?: string;
    /** Where the picture itself comes from. */
    avatar?: string;
  };
  owner?: boolean;
  chat?: { id?: number; title?: string; is_group?: boolean };
  now?: NowPlaying | null;
  queue?: Track[];
  settings?: Settings;
  /** The chat's language, and every language the bot can answer in. */
  language?: LanguageState;
  favorites?: Track[];
  history?: Track[];
  playlists?: Playlist[];
  stats?: { users?: number; chats?: number; tracks?: number };
}

export interface Shelf {
  key: string;
  title: string;
  glyph?: string;
  kind?: string;
  tracks: Track[];
}

export interface Mood {
  key: string;
  title: string;
  glyph?: string;
}

export interface HomePayload {
  hero: { headline: string; subline?: string; cover?: string };
  trending: Track[];
  shelves: Shelf[];
  moods: Mood[];
}

export interface ActionResult {
  ok: boolean;
  preview?: boolean;
  [key: string]: unknown;
}

/* ── owner journal ──────────────────────────────────────────────────────── */
export type JournalLevel = "debug" | "info" | "ok" | "warn" | "error";

export interface JournalEvent {
  seq: number;
  ts: number;
  level: JournalLevel;
  scope: string;
  message: string;
  meta: Record<string, unknown>;
}

export interface JournalStats {
  seq: number;
  buffered: number;
  counts: Partial<Record<JournalLevel, number>>;
  errors: number;
  warnings: number;
  uptime: number;
  file: string;
}

export interface SystemSnapshot {
  version: string;
  uptime: number;
  storage: string;
  streaming: boolean;
  resolver: boolean;
  downloader: boolean;
  handlers: number;
  chats: number;
  playing: number;
  watchdog: { checks?: number; reconnects?: number; last?: string | null; last_error?: string };
  keepalive: { enabled?: boolean; runs?: number; last_ok?: number | null; last_status?: number | null };
}

export interface JournalPayload {
  ok: boolean;
  events: JournalEvent[];
  stats: JournalStats;
  system: SystemSnapshot;
}
