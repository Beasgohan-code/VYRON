export type View = "home" | "search" | "library" | "queue" | "playlists" | "rooms" | "profile";

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

export interface AppState {
  ok: boolean;
  preview?: boolean;
  version?: string;
  bot?: string;
  streaming?: boolean;
  user?: { id?: number; name?: string; username?: string };
  chat?: { id?: number; title?: string; is_group?: boolean };
  now?: NowPlaying | null;
  queue?: Track[];
  settings?: Settings;
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
