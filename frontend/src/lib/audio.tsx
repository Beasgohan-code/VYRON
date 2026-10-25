import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, telegram } from "./api";
import { thumbFor } from "./format";
import { enqueue as enqueueTrack, keyOf, move as moveInQueue, nextIndex } from "./queueops";
import type { Repeat } from "./queueops";
import { buildSession, clearSession, readSession, writeSession, type SavedSession } from "./session";
import type { Track } from "./types";

export type { Repeat } from "./queueops";

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
  /** Seconds of the current track the browser has buffered. */
  buffered: number;
  /** The queue this device last left behind, if any. */
  saved: SavedSession | null;
  /**
   * Which engine is actually serving the current track's bytes ("jiosaavn"
   * when YouTube refused this server and the song is playing from a
   * catalogue). Empty while unknown.
   */
  servedBy: string;
  /* actions */
  play: (track: Track, list?: Track[]) => void;
  toggle: () => void;
  next: (auto?: boolean) => void;
  prev: () => void;
  seek: (seconds: number) => void;
  seekBy: (delta: number) => void;
  setVolume: (value: number) => void;
  setRate: (value: number) => void;
  /** Even out loud and quiet tracks with a compressor. Off by default. */
  setNormalise: (value: boolean) => void;
  normalising: boolean;
  toggleMute: () => void;
  cycleRepeat: () => void;
  toggleShuffle: () => void;
  enqueue: (track: Track, playNext?: boolean) => void;
  removeAt: (index: number) => void;
  move: (from: number, to: number) => void;
  jumpTo: (index: number) => void;
  clear: () => void;
  /** Pick up where this device left off — paused, at the saved position. */
  resumeSession: () => void;
  dismissSession: () => void;
  /** Try the current track again (a resolver hiccup, an expired URL). */
  retry: () => void;
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
  const compressorRef = useRef<DynamicsCompressorNode | null>(null);
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
  const [buffered, setBuffered] = useState(0);
  const [normalising, setNormalising] = useState(() => read("vyron:normalise", "0") === "1");
  const initialSession = readSession();
  const [saved, setSaved] = useState<SavedSession | null>(initialSession);
  const [servedBy, setServedBy] = useState("");
  const servedKey = useRef("");
  const savedRef = useRef<SavedSession | null>(initialSession);

  /* one silent retry per track when the upstream URL expires mid-stream */
  const retry = useRef<{ key: string; attempts: number }>({ key: "", attempts: 0 });
  /* monotonically increasing load id: stale loads must not touch the element */
  const loadSeq = useRef(0);

  /* keep the latest values available to the <audio> event handlers */
  const normalisingRef = useRef(normalising);
  normalisingRef.current = normalising;

  const latest = useRef({ queue, track, repeat, shuffle, volume, muted, rate, position, duration });
  latest.current = { queue, track, repeat, shuffle, volume, muted, rate, position, duration };

  const el = useCallback((): HTMLAudioElement => {
    if (!element.current) {
      const audio = new Audio();
      audio.preload = "auto";
      audio.setAttribute("playsinline", "");
      // Telegram's iOS webview will not reliably start a detached element:
      // it has to be in the document, and it has to be silent-looking. This is
      // the difference between "the app plays music" and "the app makes no
      // sound on an iPhone".
      audio.style.display = "none";
      audio.setAttribute("aria-hidden", "true");
      audio.volume = volume;
      audio.muted = muted;
      audio.playbackRate = rate;
      document.body.appendChild(audio);
      element.current = audio;
    }
    return element.current;
  }, [volume, muted, rate]);

  /* ── provenance: ask the server which engine serves this track ───────────
     The substitution tier can switch a YouTube request to a catalogue copy on
     the server side, and the app should be able to say so instead of implying
     YouTube. One request per track, cached by the browser, never blocking. */
  useEffect(() => {
    const key = keyOf(track);
    if (!key) {
      servedKey.current = "";
      setServedBy("");
      return;
    }
    if (servedKey.current === key) return;
    servedKey.current = key;
    setServedBy("");
    if (typeof fetch !== "function") return;
    let cancelled = false;
    void fetch(infoUrl(track as Track))
      .then((response) => response.json())
      .then((info: { served_by?: string; source?: string }) => {
        if (cancelled || keyOf(track) !== key) return;
        const engine = String(info?.served_by || info?.source || "").toLowerCase();
        setServedBy(engine === "youtube" ? "" : engine);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [track]);

  /* ── audio graph: lazy, and only when something actually needs it ─────── */
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
      // The compressor sits in the path whether or not it is doing anything:
      // inserting it later would mean rebuilding the whole graph mid-track.
      const compressor = context.createDynamicsCompressor();
      const bypass = !normalisingRef.current;
      compressor.threshold.value = bypass ? 0 : -24;
      compressor.knee.value = bypass ? 0 : 30;
      compressor.ratio.value = bypass ? 1 : 4;
      compressor.attack.value = 0.003;
      compressor.release.value = 0.25;
      compressorRef.current = compressor;
      source.connect(compressor);
      compressor.connect(node);
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
      // A finished track repeats only when the *track* ended by itself; a tap
      // on "next" should always move on, even with repeat-one set.
      const decision = nextIndex(list, current, {
        repeat: auto ? mode : mode === "one" ? "off" : mode,
        shuffle: on,
      });
      if (decision === "repeat") {
        const audio = el();
        audio.currentTime = 0;
        void audio.play().catch(() => undefined);
        return;
      }
      if (decision === null) {
        setPlaying(false);
        return;
      }
      const upcoming = list[decision];
      if (upcoming) void load(upcoming, list);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [el]
  );

  const load = useCallback(
    async (next: Track, list?: Track[], options: { autoplay?: boolean; at?: number } = {}) => {
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

      const at = Math.max(0, Number(options.at) || 0);
      if (at) {
        // Seek once the browser knows the length; seeking earlier is ignored
        // by every mobile webview worth supporting.
        const jump = () => {
          try {
            audio.currentTime = at;
          } catch {
            /* the track may already be gone */
          }
        };
        if (audio.readyState >= 1) jump();
        else audio.addEventListener("loadedmetadata", jump, { once: true });
        setPosition(at);
      }

      if (options.autoplay === false) {
        // A restored session loads paused: starting audio without a tap is
        // blocked by mobile browsers, and being blocked looks like a failure.
        try {
          audio.src = streamUrl(next);
        } catch {
          /* noop */
        }
        if (!stale()) {
          setLoading(false);
          setPlaying(false);
        }
        return;
      }

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
    const onTime = () => {
      setPosition(audio.currentTime || 0);
      try {
        const ranges = audio.buffered;
        setBuffered(ranges.length ? ranges.end(ranges.length - 1) : 0);
      } catch {
        setBuffered(0);
      }
    };
    const onProgress = () => {
      try {
        const ranges = audio.buffered;
        if (ranges.length) setBuffered(ranges.end(ranges.length - 1));
      } catch {
        /* ignore */
      }
    };
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
    audio.addEventListener("progress", onProgress);
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
      audio.removeEventListener("progress", onProgress);
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

  /* ── session: remember where this device was, every few seconds ──────── */
  useEffect(() => {
    const timer = window.setInterval(() => {
      const { track: current, queue: list, repeat, shuffle, volume, muted, rate, position } = latest.current;
      if (!current || !list.length) return;
      const session = buildSession({
        queue: list,
        track: current,
        position,
        rate,
        volume,
        muted,
        repeat,
        shuffle,
      });
      if (!session) return;
      writeSession(session);
      // Re-rendering every five seconds for an unchanged queue is waste; the
      // card only needs to know when the *track* or the index moved.
      const previous = savedRef.current;
      const changed =
        !previous ||
        previous.index !== session.index ||
        keyOf(previous.queue[previous.index]) !== keyOf(session.queue[session.index]);
      if (changed) {
        savedRef.current = session;
        setSaved(session);
      }
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  /* ── next-track prefetch: the resolve is the slow part of a start ─────── */
  const prefetched = useRef("");
  useEffect(() => {
    if (!track || !playing) return;
    const total = duration || track.duration || 0;
    if (!total) return;
    const remaining = total - position;
    // Warm it 25 s before the end: early enough to cover a cold resolve,
    // late enough that skipping around does not hammer the server.
    if (remaining > 25 || remaining < 1) return;
    const decision = nextIndex(queue, track, { repeat, shuffle });
    if (decision === null || decision === "repeat") return;
    const upcoming = queue[decision];
    const key = keyOf(upcoming);
    if (!key || prefetched.current === key) return;
    prefetched.current = key;
    void fetch(streamUrl(upcoming), {
      headers: { Range: "bytes=0-1" },
      cache: "no-store",
      credentials: "same-origin",
    }).catch(() => undefined);
  }, [track, playing, position, duration, queue, repeat, shuffle]);

  /* ── OS / lock-screen controls ───────────────────────────────────────── */
  useEffect(() => {
    const media = navigator.mediaSession;
    if (!media || !track) return;
    // The lock screen asks for artwork by URL and fetches it without our
    // headers, so it must be a public, cacheable URL on our own origin — the
    // same `/api/art` the tiles use, at the widest size we render.
    const art = thumbFor(track);
    try {
      media.metadata = new MediaMetadata({
        title: track.title,
        artist: track.uploader || "VYRON",
        album: "VYRON",
        artwork: art
          ? [
              { src: `${art}?s=600`, sizes: "600x600", type: "image/webp" },
              { src: `${art}?s=300`, sizes: "300x300", type: "image/webp" },
            ]
          : [],
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
      media.setActionHandler("seekbackward", (details) => {
        const audio = el();
        audio.currentTime = Math.max(0, audio.currentTime - (details.seekOffset ?? 10));
      });
      media.setActionHandler("seekforward", (details) => {
        const audio = el();
        const limit = Number.isFinite(audio.duration) ? audio.duration : audio.currentTime + 10;
        audio.currentTime = Math.min(limit, audio.currentTime + (details.seekOffset ?? 10));
      });
      media.setActionHandler("stop", () => {
        el().pause();
        el().currentTime = 0;
      });
    } catch {
      /* older Telegram webviews */
    }
  }, [advance, el, track]);

  useEffect(() => {
    const media = navigator.mediaSession;
    if (!media) return;
    try {
      media.playbackState = playing ? "playing" : "paused";
    } catch {
      /* older webviews */
    }
  }, [playing]);

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

  const enqueue = useCallback(
    (next: Track, playNext = false) => {
      setQueue((list) =>
        enqueueTrack(list, next, { next: playNext, current: latest.current.track })
      );
      toast?.(playNext ? "Playing next" : "Added to queue", "success");
    },
    [toast]
  );

  const removeAt = useCallback((index: number) => {
    setQueue((list) => (index >= 0 && index < list.length ? list.filter((_, position) => position !== index) : list));
  }, []);

  const move = useCallback((from: number, to: number) => {
    setQueue((list) => moveInQueue(list, from, to));
  }, []);

  const resumeSession = useCallback(() => {
    const session = latest.current.queue.length ? null : saved;
    if (!session) return;
    const next = session.queue[session.index];
    if (!next) return;
    setRepeat(session.repeat);
    setShuffle(session.shuffle);
    void load(next, session.queue, { autoplay: false, at: session.position });
    toast?.("Back where you left off", "success");
  }, [load, saved, toast]);

  const dismissSession = useCallback(() => {
    savedRef.current = null;
    setSaved(null);
    clearSession();
  }, []);

  const retryTrack = useCallback(() => {
    const current = latest.current.track;
    if (current) void load(current, latest.current.queue);
  }, [load]);

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

  const setNormalise = useCallback(
    (value: boolean) => {
      setNormalising(value);
      write("vyron:normalise", value ? "1" : "0");
      // Turning it on needs the graph to exist; the click is a user gesture, so
      // this is the one moment a browser will let an AudioContext start.
      const node = compressorRef.current ?? (analyser() ? compressorRef.current : null);
      if (!node) return;
      node.threshold.value = value ? -24 : 0;
      node.knee.value = value ? 30 : 0;
      node.ratio.value = value ? 4 : 1;
    },
    [analyser]
  );

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
      buffered,
      repeat,
      shuffle,
      expanded,
      saved,
      servedBy,
      play,
      toggle,
      next: advance,
      prev,
      seek,
      seekBy,
      setVolume,
      setRate,
      setNormalise,
      normalising,
      toggleMute: () => setMuted((value) => !value),
      cycleRepeat,
      toggleShuffle: () => setShuffle((value) => !value),
      enqueue,
      removeAt,
      move,
      jumpTo,
      clear,
      resumeSession,
      dismissSession,
      retry: retryTrack,
      setExpanded,
      isCurrent: (candidate) => Boolean(candidate) && keyOf(candidate) === keyOf(track),
      analyser,
    }),
    [
      track, queue, playing, loading, error, position, duration, volume, muted, rate, buffered,
      repeat, shuffle, expanded, saved, servedBy, play, toggle, advance, prev, seek, seekBy, setVolume,
      setRate, setNormalise, normalising, cycleRepeat, enqueue, removeAt, move, jumpTo, clear,
      resumeSession, dismissSession,
      retryTrack, analyser,
    ]
  );
}

/** Resolve a query (or track) into a playable Track via /api/search. */
export async function resolveTrack(target: string | Track): Promise<Track | null> {
  if (typeof target !== "string") return target;
  const payload = await api.search(target, 1);
  return payload.results?.[0] ?? null;
}
