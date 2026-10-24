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
  /** Playback speed, 0.5×–2×. Persisted per device. */
  rate: number;
  /* actions */
  play: (track: Track, list?: Track[]) => void;
  toggle: () => void;
  next: (auto?: boolean) => void;
  prev: () => void;
  seek: (seconds: number) => void;
  seekBy: (delta: number) => void;
  setVolume: (value: number) => void;
  setRate: (value: number) => void;
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
  const [rate, setRateState] = useState(() => {
    const stored = Number(read("vyron:rate", "1"));
    return Number.isFinite(stored) && stored >= 0.5 && stored <= 2 ? stored : 1;
  });
  const [repeat, setRepeat] = useState<Repeat>(() => read("vyron:repeat", "off") as Repeat);
  const [shuffle, setShuffle] = useState(() => read("vyron:shuffle", "0") === "1");
  const [expanded, setExpanded] = useState(false);

  /* one silent retry per track when the upstream URL expires mid-stream */
  const retry = useRef<{ key: string; attempts: number }>({ key: "", attempts: 0 });
  /* monotonically increasing load id: stale loads must not touch the element */
  const loadSeq = useRef(0);

  /* keep the latest values available to the <audio> event handlers */
  const latest = useRef({ queue, track, repeat, shuffle, volume, muted, rate });
  latest.current = { queue, track, repeat, shuffle, volume, muted, rate };

  const el = useCallback((): HTMLAudioElement => {
    if (!element.current) {
      const audio = new Audio();
      audio.preload = "auto";
      audio.setAttribute("playsinline", "");
      audio.volume = volume;
      audio.muted = muted;
      audio.playbackRate = rate;
      element.current = audio;
    }
    return element.current;
  }, [volume, muted, rate]);

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
      const seq = (loadSeq.current += 1);
      const stale = () => seq !== loadSeq.current;

      setError(null);
      setLoading(true);

      // Start inside the tap. Awaiting the preflight first used to break the
      // user-gesture chain in Telegram's iOS webview — the element then refused
      // to start, which looked exactly like "the app cannot play songs".
      setTrack(next);
      if (list) setQueue(list);
      setPosition(0);
      setDuration(next.duration ?? 0);
      retry.current = { key: keyOf(next), attempts: 0 };

      try {
        audio.src = streamUrl(next);
        await audio.play();
        if (!stale()) setPlaying(true);
      } catch (cause) {
        // Autoplay blocks and unsupported sources land here; the UI stays usable.
        if (stale()) return;
        setPlaying(false);
        const blocked = cause instanceof DOMException && cause.name === "NotAllowedError";
        setError(blocked ? "tap play to start" : "could not start this track");
        toast?.(
          blocked ? "Tap play to start the audio" : "That track would not start — try another",
          "info"
        );
      } finally {
        if (!stale()) setLoading(false);
      }

      // The preflight now runs *alongside* playback: it cannot block the start,
      // but its answer is still the clearest reason we can show when the server
      // knows the track is unavailable.
      if (typeof fetch !== "function") return;
      try {
        const probe = await fetch(infoUrl(next));
        const info = (await probe.json()) as {
          ok?: boolean;
          playable?: boolean;
          reason?: string;
          error?: string;
        };
        if (stale()) return;
        const dead = info && (info.playable === false || info.ok === false);
        if (!dead) return;
        // Only take over the UI if nothing is actually playing yet.
        const silent = !audio.currentTime || audio.paused;
        if (!silent) return;
        audio.pause();
        setPlaying(false);
        const why =
          info.error === "unauthorized"
            ? "Open VYRON inside Telegram (or unlock this browser) to play"
            : info.reason || info.error || "this track cannot be streamed right now";
        setError(why);
        toast?.(why, "error");
      } catch {
        /* the probe is a nicety: it must never break playback */
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
        try {
          audio.src = streamUrl(current, Date.now());
          void audio.play().catch(() => {
            setLoading(false);
            setError("this track will not load");
          });
        } catch {
          setLoading(false);
          setError("this track will not load");
        }
        return;
      }
      setLoading(false);
      setError("this track will not load");
      // The media element gives us no reason, so ask the server what it knows
      // and surface that instead of a generic failure.
      if (typeof fetch === "function") {
        void fetch(infoUrl(current))
          .then((response) => response.json())
          .then((info: { reason?: string; error?: string; playable?: boolean }) => {
            if (keyOf(latest.current.track) !== key) return;
            const why = info?.reason || (info?.playable === false ? info.error : "");
            if (why) setError(why);
          })
          .catch(() => undefined);
      }
      toast?.("That track will not load — skipping ahead", "error");
      setTimeout(() => {
        // only auto-skip if the listener is still sitting on this track
        if (keyOf(latest.current.track) === key) advance(true);
      }, 1200);
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
        artwork: track.thumbnail ? [{ src: track.thumbnail, sizes: "512x512", type: "image/jpeg" }] : [],
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

  /* Lock-screen scrubber: without this the OS shows a play button and no bar. */
  useEffect(() => {
    const media = navigator.mediaSession;
    if (!media || typeof media.setPositionState !== "function") return;
    const audio = el();
    const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    if (!track || !duration) {
      try {
        media.setPositionState();
      } catch {
        /* unsupported */
      }
      return;
    }
    try {
      media.setPositionState({
        duration,
        position: Math.min(Math.max(0, audio.currentTime || 0), duration),
        playbackRate: audio.playbackRate || 1,
      });
    } catch {
      /* webview without a scrubber */
    }
  }, [el, track, position, playing]);

  /* ── public actions ──────────────────────────────────────────────────── */
  const play = useCallback(
    (next: Track, list?: Track[]) => {
      if (list) {
        void load(next, list);
        return;
      }
      const queue = latest.current.queue;
      const queued = queue.some((item) => keyOf(item) === keyOf(next));
      // A track picked from search jumps to the front; one that is already in
      // the queue plays from its place, keeping the rest of the order intact.
      void load(next, queued ? queue : [next, ...queue]);
    },
    [load]
  );

  const toggle = useCallback(() => {
    const audio = el();
    const current = latest.current.track;
    if (!current) return;
    // A media error leaves the element stuck on a dead source: reload instead
    // of asking the browser to replay it.
    if (audio.error) {
      void load(current);
      return;
    }
    if (audio.paused) void audio.play().catch(() => undefined);
    else audio.pause();
  }, [el, load]);

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

  const setRate = useCallback((value: number) => {
    const next = Math.min(2, Math.max(0.5, Math.round(value * 100) / 100));
    setRateState(next);
    write("vyron:rate", String(next));
    const audio = element.current;
    if (audio) audio.playbackRate = next;
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
      rate,
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
      setRate,
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
      track, queue, playing, loading, error, position, duration, volume, muted, rate, repeat,
      shuffle, expanded, play, toggle, advance, prev, seek, seekBy, setVolume, setRate, cycleRepeat,
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
