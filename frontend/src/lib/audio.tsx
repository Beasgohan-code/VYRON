import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, telegram } from "./api";
import type { Track } from "./types";

export type Repeat = "off" | "one" | "all";

export interface AudioEngine {
  /* state */
  track: Track | null;
  queue: Track[];
  playing: boolean;
  loading: boolean;
  error: string | null;
  position: number;
  duration: number;
  volume: number;
  muted: boolean;
  repeat: Repeat;
  shuffle: boolean;
  expanded: boolean;
  /* actions */
  play: (track: Track, list?: Track[]) => void;
  toggle: () => void;
  next: (auto?: boolean) => void;
  prev: () => void;
  seek: (seconds: number) => void;
  seekBy: (delta: number) => void;
  setVolume: (value: number) => void;
  toggleMute: () => void;
  cycleRepeat: () => void;
  toggleShuffle: () => void;
  enqueue: (track: Track, playNext?: boolean) => void;
  removeAt: (index: number) => void;
  jumpTo: (index: number) => void;
  clear: () => void;
  setExpanded: (value: boolean) => void;
  isCurrent: (track?: Track | null) => boolean;
  /** Web Audio analyser for the shared <audio> element (null if unsupported). */
  analyser: () => AnalyserNode | null;
}

const read = (key: string, fallback: string): string => {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
};

const write = (key: string, value: string): void => {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode */
  }
};

const keyOf = (track?: Track | null): string => String(track?.id ?? track?.title ?? "");

function authParams(): URLSearchParams {
  const params = new URLSearchParams();
  const token = read("vyron:token", "");
  const initData = telegram()?.initData ?? "";
  if (token) params.set("t", token);
  if (initData) params.set("init_data", initData);
  return params;
}

function streamUrl(track: Track, attempt = 0): string {
  const id = encodeURIComponent(String(track.id ?? ""));
  const params = authParams();
  if (attempt) params.set("r", String(attempt));
  const suffix = params.toString();
  return `/api/stream/${id}${suffix ? `?${suffix}` : ""}`;
}

function infoUrl(track: Track): string {
  const id = encodeURIComponent(String(track.id ?? ""));
  const suffix = authParams().toString();
  return `/api/audio/${id}${suffix ? `?${suffix}` : ""}`;
}

/**
 * A single <audio> element shared by the whole app: the Mini App plays music
 * itself (Spotify-style) while the bot keeps owning the voice chat.
 */
export function useAudioEngine(toast?: (message: string, tone?: "info" | "error" | "success") => void): AudioEngine {
  const element = useRef<HTMLAudioElement | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const [track, setTrack] = useState<Track | null>(null);
  const [queue, setQueue] = useState<Track[]>([]);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolumeState] = useState(() => Number(read("vyron:volume", "0.9")));
  const [muted, setMuted] = useState(() => read("vyron:muted", "0") === "1");
  const [repeat, setRepeat] = useState<Repeat>(() => read("vyron:repeat", "off") as Repeat);
  const [shuffle, setShuffle] = useState(() => read("vyron:shuffle", "0") === "1");
  const [expanded, setExpanded] = useState(false);

  /* one silent retry per track when the upstream URL expires mid-stream */
  const retry = useRef<{ key: string; attempts: number }>({ key: "", attempts: 0 });

  /* keep the latest values available to the <audio> event handlers */
  const latest = useRef({ queue, track, repeat, shuffle, volume, muted });
  latest.current = { queue, track, repeat, shuffle, volume, muted };

  const el = useCallback((): HTMLAudioElement => {
    if (!element.current) {
      const audio = new Audio();
      audio.preload = "auto";
      audio.setAttribute("playsinline", "");
      audio.volume = volume;
      audio.muted = muted;
      element.current = audio;
    }
    return element.current;
  }, [volume, muted]);

  /* ── audio analyser (lazy: only the 3D visualiser asks for it) ────────── */
  const analyser = useCallback((): AnalyserNode | null => {
    if (analyserRef.current) return analyserRef.current;
    try {
      const Ctor =
        window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor || !element.current) return null;
      const context = new Ctor();
      const source = context.createMediaElementSource(element.current);
      const node = context.createAnalyser();
      node.fftSize = 128;
      node.smoothingTimeConstant = 0.82;
      source.connect(node);
      node.connect(context.destination);
      // A suspended context would silence playback, so nudge it on every play.
      const wake = () => {
        if (context.state !== "running") void context.resume().catch(() => undefined);
      };
      element.current.addEventListener("play", wake);
      wake();
      contextRef.current = context;
      analyserRef.current = node;
      return node;
    } catch {
      return null;
    }
  }, []);

  useEffect(
    () => () => {
      analyserRef.current = null;
      contextRef.current?.close().catch(() => undefined);
      contextRef.current = null;
    },
    []
  );

  const advance = useCallback(
    (auto = false) => {
      const { queue: list, track: current, repeat: mode, shuffle: on } = latest.current;
      if (!list.length) {
        setPlaying(false);
        return;
      }
      const index = list.findIndex((item) => keyOf(item) === keyOf(current));
      if (auto && mode === "one" && current) {
        const audio = el();
        audio.currentTime = 0;
        void audio.play().catch(() => undefined);
        return;
      }
      let nextIndex = index + 1;
      if (on) {
        const pool = list.map((_, position) => position).filter((position) => position !== index);
        nextIndex = pool.length ? pool[Math.floor(Math.random() * pool.length)] : 0;
      } else if (nextIndex >= list.length) {
        if (mode === "all") nextIndex = 0;
        else {
          setPlaying(false);
          return;
        }
      }
      const upcoming = list[nextIndex];
      if (upcoming) {
        void load(upcoming, list);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [el]
  );

  const load = useCallback(
    async (next: Track, list?: Track[]) => {
      const audio = el();
      setTrack(next);
      if (list) setQueue(list);
      setError(null);
      setLoading(true);
      setPosition(0);
      setDuration(next.duration ?? 0);
      // Preflight tells us whether the server can even resolve this track; a
      // generic "playback blocked" toast wastes the listener's time.
      if (typeof fetch === "function") {
        try {
          const probe = await fetch(infoUrl(next));
          const info = (await probe.json()) as { playable?: boolean; reason?: string };
          if (info && info.playable === false) {
            setPlaying(false);
            setError(info.reason || "this track cannot be streamed right now");
            toast?.(info.reason || "Streaming is not available here — try /song in the bot", "error");
            setLoading(false);
            return;
          }
        } catch {
          /* the probe is a nicety: never block playback on it */
        }
      }
      retry.current = { key: keyOf(next), attempts: 0 };
      try {
        audio.src = streamUrl(next);
        audio.currentTime = 0;
        await audio.play();
        setPlaying(true);
      } catch (cause) {
        // Autoplay blocks and unsupported sources land here; the UI stays usable.
        setPlaying(false);
        const blocked = cause instanceof DOMException && cause.name === "NotAllowedError";
        setError(blocked ? "tap play to start" : "could not start this track");
        toast?.(blocked ? "Tap play to start the audio" : "That track would not start — try another", "info");
      } finally {
        setLoading(false);
      }
    },
    [el, toast]
  );

  /* ── element wiring ──────────────────────────────────────────────────── */
  useEffect(() => {
    const audio = el();
    const onTime = () => setPosition(audio.currentTime || 0);
    const onMeta = () => setDuration(audio.duration || latest.current.track?.duration || 0);
    const onEnded = () => advance(true);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onWaiting = () => setLoading(true);
    const onPlaying = () => setLoading(false);
    const onError = () => {
      const current = latest.current.track;
      const key = keyOf(current);
      if (!current || !key) return;
      if (retry.current.key !== key) retry.current = { key, attempts: 0 };
      if (retry.current.attempts < 1) {
        retry.current.attempts += 1;
        setLoading(true);
        audio.src = streamUrl(current, Date.now());
        audio.currentTime = 0;
        void audio.play().catch(() => {
          setLoading(false);
          setError("this track will not load");
        });
        return;
      }
      setLoading(false);
      setError("this track will not load");
      toast?.("That track will not load — skipping ahead", "error");
      setTimeout(() => advance(true), 1200);
    };
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("loadedmetadata", onMeta);
    audio.addEventListener("durationchange", onMeta);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("waiting", onWaiting);
    audio.addEventListener("playing", onPlaying);
    audio.addEventListener("error", onError);
    return () => {
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("loadedmetadata", onMeta);
      audio.removeEventListener("durationchange", onMeta);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("waiting", onWaiting);
      audio.removeEventListener("playing", onPlaying);
      audio.removeEventListener("error", onError);
    };
  }, [advance, el, toast]);

  useEffect(() => {
    const audio = el();
    audio.volume = Math.min(1, Math.max(0, volume));
    audio.muted = muted;
    write("vyron:volume", String(volume));
    write("vyron:muted", muted ? "1" : "0");
  }, [el, volume, muted]);

  useEffect(() => {
    write("vyron:repeat", repeat);
    write("vyron:shuffle", shuffle ? "1" : "0");
  }, [repeat, shuffle]);

  /* ── OS / lock-screen controls ───────────────────────────────────────── */
  useEffect(() => {
    const media = navigator.mediaSession;
    if (!media || !track) return;
    try {
      media.metadata = new MediaMetadata({
        title: track.title,
        artist: track.uploader || "VYRON",
        album: "VYRON",
        artwork: track.thumbnail ? [{ src: track.thumbnail, sizes: "512x512" }] : [],
      });
      media.setActionHandler("play", () => {
        void el().play().catch(() => undefined);
      });
      media.setActionHandler("pause", () => el().pause());
      media.setActionHandler("nexttrack", () => advance());
      media.setActionHandler("previoustrack", () => {
        const audio = el();
        if (audio.currentTime > 4) {
          audio.currentTime = 0;
          return;
        }
        advance();
      });
      media.setActionHandler("seekto", (details) => {
        if (typeof details.seekTime === "number") el().currentTime = details.seekTime;
      });
    } catch {
      /* older Telegram webviews */
    }
  }, [advance, el, track]);

  /* ── public actions ──────────────────────────────────────────────────── */
  const play = useCallback(
    (next: Track, list?: Track[]) => {
      void load(next, list ?? [next, ...latest.current.queue.filter((item) => keyOf(item) !== keyOf(next))]);
    },
    [load]
  );

  const toggle = useCallback(() => {
    const audio = el();
    if (!latest.current.track) return;
    if (audio.paused) void audio.play().catch(() => undefined);
    else audio.pause();
  }, [el]);

  const prev = useCallback(() => {
    const audio = el();
    if (audio.currentTime > 4) {
      audio.currentTime = 0;
      return;
    }
    const { queue: list, track: current } = latest.current;
    const index = list.findIndex((item) => keyOf(item) === keyOf(current));
    const previous = list[index - 1] ?? list[list.length - 1];
    if (previous) void load(previous, list);
  }, [el, load]);

  const seek = useCallback(
    (seconds: number) => {
      const audio = el();
      const target = Math.max(0, Math.min(seconds, audio.duration || seconds));
      audio.currentTime = target;
      setPosition(target);
    },
    [el]
  );

  const seekBy = useCallback(
    (delta: number) => {
      seek(el().currentTime + delta);
    },
    [el, seek]
  );

  const enqueue = useCallback((next: Track, playNext = false) => {
    setQueue((list) => {
      if (list.some((item) => keyOf(item) === keyOf(next))) return list;
      if (!playNext) return [...list, next];
      const current = latest.current.track;
      const index = list.findIndex((item) => keyOf(item) === keyOf(current));
      const copy = [...list];
      copy.splice(Math.max(0, index + 1), 0, next);
      return copy;
    });
    toast?.(playNext ? "Playing next" : "Added to queue", "success");
  }, [toast]);

  const removeAt = useCallback((index: number) => {
    setQueue((list) => list.filter((_, position) => position !== index));
  }, []);

  const jumpTo = useCallback(
    (index: number) => {
      const next = latest.current.queue[index];
      if (next) void load(next, latest.current.queue);
    },
    [load]
  );

  const clear = useCallback(() => {
    el().pause();
    setQueue(latest.current.track ? [latest.current.track] : []);
    toast?.("Queue cleared", "info");
  }, [el, toast]);

  const setVolume = useCallback((value: number) => {
    setVolumeState(Math.min(1, Math.max(0, value)));
    setMuted(value <= 0);
  }, []);

  const cycleRepeat = useCallback(() => {
    setRepeat((mode) => (mode === "off" ? "all" : mode === "all" ? "one" : "off"));
  }, []);

  return useMemo<AudioEngine>(
    () => ({
      track,
      queue,
      playing,
      loading,
      error,
      position,
      duration,
      volume,
      muted,
      repeat,
      shuffle,
      expanded,
      play,
      toggle,
      next: advance,
      prev,
      seek,
      seekBy,
      setVolume,
      toggleMute: () => setMuted((value) => !value),
      cycleRepeat,
      toggleShuffle: () => setShuffle((value) => !value),
      enqueue,
      removeAt,
      jumpTo,
      clear,
      setExpanded,
      isCurrent: (candidate) => Boolean(candidate) && keyOf(candidate) === keyOf(track),
      analyser,
    }),
    [
      track, queue, playing, loading, error, position, duration, volume, muted, repeat,
      shuffle, expanded, play, toggle, advance, prev, seek, seekBy, setVolume, cycleRepeat,
      enqueue, removeAt, jumpTo, clear, analyser,
    ]
  );
}

/** Resolve a query (or track) into a playable Track via /api/search. */
export async function resolveTrack(target: string | Track): Promise<Track | null> {
  if (typeof target !== "string") return target;
  const payload = await api.search(target, 1);
  return payload.results?.[0] ?? null;
}
