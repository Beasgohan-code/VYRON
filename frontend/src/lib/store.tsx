import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, api, haptic, notify, pollNow, setToken } from "./api";
import { primeAvatar } from "./avatar";
import {
  applyViewport,
  bootShell,
  paintChrome,
  startTarget,
  syncScheme,
  watchClient,
} from "./telegram";
import { resolveTrack, useAudioEngine, type AudioEngine } from "./audio";
import type { AppState, HomePayload, Playlist, Room, Track, View } from "./types";

export type ThemeName = "beat" | "telegram" | "system";
export type AccentName = "violet" | "blue" | "cyan" | "green" | "pink" | "amber";
export type SearchFilter = "all" | "songs" | "playlists" | "artists";
export type LibraryFilter = "liked" | "playlists" | "history";

export type ModalRequest =
  | { type: "download"; query?: string; kind?: "audio" | "video" }
  | { type: "new-playlist" }
  | { type: "add-to-playlist"; track: Track }
  | { type: "track"; track: Track };

interface Store {
  /* data */
  state: AppState | null;
  home: HomePayload | null;
  rooms: Room[];
  playlists: Playlist[];
  results: Track[];
  /* navigation */
  view: View;
  setView: (view: View) => void;
  query: string;
  searchFilter: SearchFilter;
  setSearchFilter: (filter: SearchFilter) => void;
  libraryFilter: LibraryFilter;
  setLibraryFilter: (filter: LibraryFilter) => void;
  selectedPlaylist: Playlist | null;
  openPlaylist: (playlist: Playlist | null) => void;
  /* appearance */
  theme: ThemeName;
  setTheme: (theme: ThemeName) => void;
  accent: AccentName;
  setAccent: (accent: AccentName) => void;
  normalise: boolean;
  setNormalise: (value: boolean) => void;
  /* feedback */
  toastMessage: string;
  toast: (message: string, tone?: "info" | "error" | "success") => void;
  toastTone: "info" | "error" | "success";
  modal: ModalRequest | null;
  openModal: (request: ModalRequest) => void;
  closeModal: () => void;
  /* actions */
  act: <T = Record<string, unknown>>(action: string, value?: unknown) => Promise<(T & { preview?: boolean }) | null>;
  play: (value: string | Track | undefined, mode?: "play" | "play_now") => Promise<void>;
  runSearch: (query: string, remember?: boolean, more?: boolean) => Promise<void>;
  /** True while this query has more results than the rows on screen. */
  canSearchMore: boolean;
  searching: boolean;
  /** "ok" · "locked" (no Telegram session) · "offline" (server unreachable) */
  access: "ok" | "locked" | "offline";
  loadMix: (key: string) => Promise<void>;
  refreshState: () => Promise<void>;
  refreshHome: () => Promise<void>;
  refreshRooms: () => Promise<void>;
  /** Point the app at a voice chat the user administers. */
  attachRoom: (chatId: number) => Promise<boolean>;
  refreshPlaylists: () => Promise<void>;
  recent: string[];
  rememberSearch: (term: string) => void;
  /* in-app playback (Spotify-style) */
  audio: AudioEngine;
  cast: (value: string | Track | undefined, mode?: "play" | "play_now") => Promise<void>;
  /* playback helpers */
  dragging: boolean;
  setDragging: (value: boolean) => void;
  /* likes — optimistic, so the heart responds to the tap, not the network */
  isLiked: (track?: Track | null) => boolean;
  toggleLike: (track: Track) => Promise<void>;
  likeCount: number;
}

const AppContext = createContext<Store | null>(null);

/** One page of results, and how much more each "More" adds. The ceiling is
 *  what `/api/search` will hand back in a single answer. */
const SEARCH_STEP = 12;
const SEARCH_LIMIT_MAX = 36;

const readLocal = (key: string, fallback: string): string => {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
};

const writeLocal = (key: string, value: string): void => {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode */
  }
};

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState | null>(null);
  const [home, setHome] = useState<HomePayload | null>(null);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [results, setResults] = useState<Track[]>([]);
  const [searching, setSearching] = useState(false);
  const [canSearchMore, setCanSearchMore] = useState(false);
  const [access, setAccess] = useState<"ok" | "locked" | "offline">("ok");
  const [view, setViewState] = useState<View>("home");
  const [query, setQuery] = useState("");
  const [searchFilter, setSearchFilter] = useState<SearchFilter>("all");
  const [libraryFilter, setLibraryFilter] = useState<LibraryFilter>("liked");
  const [selectedPlaylist, setSelectedPlaylist] = useState<Playlist | null>(null);
  const [theme, setThemeState] = useState<ThemeName>(() => readLocal("vyron:theme", "beat") as ThemeName);
  const [accent, setAccentState] = useState<AccentName>(() => readLocal("vyron:accent", "cyan") as AccentName);
  const [normalise, setNormaliseState] = useState(() => readLocal("vyron:normalise", "0") === "1");
  const [toastMessage, setToastMessage] = useState("");
  const [toastTone, setToastTone] = useState<"info" | "error" | "success">("info");
  const [modal, setModal] = useState<ModalRequest | null>(null);
  const [recent, setRecent] = useState<string[]>(() => {
    try {
      return JSON.parse(readLocal("vyron:recent", "[]")) as string[];
    } catch {
      return [];
    }
  });
  const [dragging, setDragging] = useState(false);
  const toastTimer = useRef<number | undefined>(undefined);

  /* ── appearance ─────────────────────────────────────────────────────── */
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.accent = accent;
    // "Telegram" is a real theme now, not a label: the client's own colours
    // arrive as CSS variables, and the header must follow them.
    syncScheme();
    paintChrome();
  }, [theme, accent]);

  const setTheme = useCallback((next: ThemeName) => {
    setThemeState(next);
    writeLocal("vyron:theme", next);
  }, []);

  const setAccent = useCallback((next: AccentName) => {
    setAccentState(next);
    writeLocal("vyron:accent", next);
  }, []);



  /* ── feedback ───────────────────────────────────────────────────────── */
  const toast = useCallback((message: string, tone: "info" | "error" | "success" = "info") => {
    setToastMessage(message);
    setToastTone(tone);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToastMessage(""), 2600);
  }, []);

  const openModal = useCallback((request: ModalRequest) => {
    haptic("soft");
    setModal(request);
  }, []);

  const closeModal = useCallback(() => setModal(null), []);

  /* ── data ───────────────────────────────────────────────────────────── */
  const refreshState = useCallback(async () => {
    try {
      const payload = await api.state();
      setState(payload);
      setAccess("ok");
      // Fetch the profile picture now, so the first render that shows a face
      // already has one instead of a grey circle that fills in a beat later.
      primeAvatar(payload.user);
    } catch (error) {
      if (error instanceof ApiError) {
        setAccess(error.status === 401 ? "locked" : "offline");
        if (error.status !== 401) toast(error.message, "error");
      } else {
        setAccess("offline");
      }
    }
  }, [toast]);

  const refreshHome = useCallback(async () => {
    try {
      setHome(await api.home());
    } catch {
      setHome(null);
    }
  }, []);

  const refreshRooms = useCallback(async () => {
    try {
      const payload = await api.rooms();
      setRooms(payload.rooms ?? []);
    } catch {
      /* rooms are decorative — never block the UI */
    }
  }, []);

  const attachRoom = useCallback(
    async (chatId: number) => {
      try {
        const payload = await api.attachRoom(chatId);
        setToken(payload.token);
        await refreshState();
        toast("Now controlling that voice chat", "success");
        return true;
      } catch (error) {
        toast(error instanceof Error ? error.message : "Could not attach to that chat", "error");
        return false;
      }
    },
    [refreshState, toast]
  );

  const refreshPlaylists = useCallback(async () => {
    try {
      const payload = await api.playlists();
      setPlaylists(payload.playlists ?? []);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    // Ready before the first request: the client owns the spinner until then.
    bootShell();
    const stop = watchClient({
      onChange: () => {
        // a theme flip while the app is open must not need a reload
        applyViewport();
      },
    });
    const boot = async () => {
      await Promise.allSettled([
        refreshState(),
        api
          .home()
          .then(setHome)
          .catch(() => setHome(null)),
        refreshRooms(),
        refreshPlaylists(),
      ]);
    };
    void boot();
    return stop;
  }, [refreshState, refreshRooms, refreshPlaylists]);

  /**
   * The live poll: queue, clock and settings, nothing else.
   *
   * Merged into the existing state so the heavy lists stay put — replacing the
   * whole document every five seconds was throwing away the favourites the
   * user was looking at, and re-rendering every list on screen.
   */
  const poll = useCallback(async () => {
    try {
      const live = await pollNow();
      if (!live) return; // 304: nothing moved
      setState((previous) => (previous ? { ...previous, ...live } : (live as AppState)));
      setAccess("ok");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) setAccess("locked");
    }
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void poll();
    }, 5000);
    // Coming back to the tab should be instant, not up to five seconds late.
    const onVisible = () => {
      if (document.visibilityState === "visible") void poll();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [poll]);

  useEffect(() => {
    if (view !== "rooms" && view !== "home") return undefined;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refreshRooms();
    }, 45000);
    return () => window.clearInterval(timer);
  }, [view, refreshRooms]);

  /* ── actions ────────────────────────────────────────────────────────── */
  const act = useCallback(
    async <T,>(action: string, value?: unknown) => {
      haptic();
      try {
        const payload = await api.action<T>(action, value);
        if (payload.preview) {
          toast("Preview mode — open in Telegram to control playback");
          return payload;
        }
        await refreshState();
        return payload;
      } catch (error) {
        const message = error instanceof Error ? error.message : "Action failed";
        notify("error");
        toast(message, "error");
        return null;
      }
    },
    [refreshState, toast]
  );

  /* ── in-app playback ─────────────────────────────────────────────────── */
  const audio = useAudioEngine(toast);

  /* The engine owns the compressor, `/you` owns the preference: one call keeps
     the two in step, instead of a flag that only painted a switch. */
  const setNormalise = useCallback(
    (value: boolean) => {
      setNormaliseState(value);
      writeLocal("vyron:normalise", value ? "1" : "0");
      audio.setNormalise(value);
    },
    [audio]
  );

  const play = useCallback(
    async (value: string | Track | undefined, mode: "play" | "play_now" = "play") => {
      const clean = typeof value === "string" ? value.trim() : value;
      if (!clean) return;
      try {
        const track = await resolveTrack(clean);
        if (!track) {
          toast("Nothing playable for that", "error");
          return;
        }
        if (mode === "play_now" || !audio.track) {
          audio.play(track);
        } else {
          audio.enqueue(track);
        }
      } catch (error) {
        toast(error instanceof Error ? error.message : "Could not play that", "error");
      }
    },
    [audio, toast]
  );

  /** Send playback to the Telegram voice chat instead of this device. */
  const cast = useCallback(
    async (value: string | Track | undefined, mode: "play" | "play_now" = "play_now") => {
      const clean =
        typeof value === "string" ? value.trim() : (value?.query ?? value?.title ?? "").trim();
      if (!clean) return;
      toast(mode === "play_now" ? "Sending to the call…" : "Adding to the call queue…");
      const payload = await act(mode, clean);
      if (payload?.preview) return;
      if (payload) toast(mode === "play_now" ? "Playing in the call" : "Queued in the call", "success");
    },
    [act, toast]
  );

  /* ── likes ───────────────────────────────────────────────────────────── */
  const likedKeys = useMemo(
    () => new Set((state?.favorites ?? []).map((item) => String(item.id ?? item.title))),
    [state]
  );

  const isLiked = useCallback(
    (track?: Track | null) => (track ? likedKeys.has(String(track.id ?? track.title)) : false),
    [likedKeys]
  );

  const toggleLike = useCallback(
    async (track: Track) => {
      if (!track) return;
      const key = String(track.id ?? track.title);
      const wasLiked = likedKeys.has(key);
      haptic("light");
      // Flip the heart now; the server call below is the confirmation, not the
      // source of truth for the animation.
      setState((previous) => {
        if (!previous) return previous;
        const favorites = previous.favorites ?? [];
        return {
          ...previous,
          favorites: wasLiked
            ? favorites.filter((item) => String(item.id ?? item.title) !== key)
            : [{ ...track, saved_at: Math.floor(Date.now() / 1000) }, ...favorites],
        };
      });
      const payload = await act(
        wasLiked ? "unfavorite" : "favorite_track",
        wasLiked ? key : track
      );
      if (!payload) {
        await refreshState(); // the call failed: put the heart back
        return;
      }
      notify(wasLiked ? "success" : "success");
      toast(wasLiked ? "Removed from liked songs" : "Added to liked songs", "success");
    },
    [act, likedKeys, refreshState, toast]
  );

  const rememberSearch = useCallback((term: string) => {
    setRecent((previous) => {
      const next = [term, ...previous.filter((item) => item !== term)].slice(0, 8);
      writeLocal("vyron:recent", JSON.stringify(next));
      return next;
    });
  }, []);

  const searchSeq = useRef(0);
  /** How many results the current query has asked for — "More" widens it. */
  const searchLimit = useRef(SEARCH_STEP);

  const runSearch = useCallback(
    async (value: string, remember = true, more = false) => {
      const clean = value.trim();
      if (!clean) return;
      setQuery(clean);
      if (remember) rememberSearch(clean);
      const seq = (searchSeq.current += 1);
      setSearching(true);
      try {
        // "More" widens the same query rather than starting a new one: the rows
        // already on screen stay, and the endpoint answers with the longer list.
        const limit = more ? Math.min(SEARCH_LIMIT_MAX, searchLimit.current + SEARCH_STEP) : SEARCH_STEP;
        const payload = await api.search(clean, limit);
        if (seq !== searchSeq.current) return;
        searchLimit.current = limit;
        const found = payload.results ?? [];
        setResults(found);
        // A short answer means the source has nothing more to give, so the
        // button stops promising another page.
        setCanSearchMore(found.length >= limit && limit < SEARCH_LIMIT_MAX);
      } catch (error) {
        if (seq === searchSeq.current) {
          toast(error instanceof Error ? error.message : "Search failed", "error");
        }
      } finally {
        if (seq === searchSeq.current) setSearching(false);
      }
    },
    [rememberSearch, toast]
  );

  const loadMix = useCallback(
    async (key: string) => {
      try {
        const payload = await api.mix(key);
        setResults(payload.tracks ?? []);
        setQuery(key);
        setSearchFilter("all");
        setViewState("search");
        toast(`${payload.tracks?.length ?? 0} tracks loaded`, "success");
      } catch (error) {
        toast(error instanceof Error ? error.message : "Could not load that mix", "error");
      }
    },
    [toast]
  );

  const setView = useCallback((next: View) => {
    setViewState(next);
    haptic("soft");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const openPlaylist = useCallback((playlist: Playlist | null) => {
    setSelectedPlaylist(playlist);
    if (playlist) {
      setViewState("playlists");
      void api
        .playlists()
        .then((payload) => {
          const fresh = (payload.playlists ?? []).find((item) => item.id === playlist.id);
          if (fresh) setSelectedPlaylist(fresh);
        })
        .catch(() => undefined);
    }
  }, []);

  /**
   * `?startapp=` — a menu link like `t.me/VyronMusicBot?startapp=playlist_abc`
   * is the only way a bot message can deep-link without printing a URL, so it
   * is worth honouring. Acted on once, after the first state arrives, and only
   * when the user has not already navigated somewhere themselves.
   */
  const deepLinked = useRef(false);
  useEffect(() => {
    if (deepLinked.current || !state) return;
    const target = startTarget();
    deepLinked.current = true;
    if (!target) return;
    if (target.kind === "view") {
      setView(target.view as View);
      return;
    }
    if (target.kind === "search") {
      setQuery(target.query);
      void runSearch(target.query);
      return;
    }
    if (target.kind === "mix") {
      void loadMix(target.key);
      return;
    }
    // the playlist is not in the first payload yet, so ask for it by id
    void api
      .playlists()
      .then((payload) => {
        const found = (payload.playlists ?? []).find((item) => item.id === target.id);
        if (found) openPlaylist(found);
        else toast("That playlist is no longer saved", "error");
      })
      .catch(() => undefined);
  }, [state, setView, runSearch, loadMix, openPlaylist, toast]);

  const value = useMemo<Store>(
    () => ({
      state,
      home,
      rooms,
      playlists,
      results,
      searching,
      canSearchMore,
      access,
      view,
      setView,
      query,
      searchFilter,
      setSearchFilter,
      libraryFilter,
      setLibraryFilter,
      selectedPlaylist,
      openPlaylist,
      theme,
      setTheme,
      accent,
      setAccent,
      normalise,
      setNormalise,
      toastMessage,
      toast,
      toastTone,
      modal,
      openModal,
      closeModal,
      act,
      play,
      runSearch,
      loadMix,
      refreshState,
      refreshHome,
      refreshRooms,
      attachRoom,
      refreshPlaylists,
      recent,
      rememberSearch,
      audio,
      cast,
      dragging,
      setDragging,
      isLiked,
      toggleLike,
      likeCount: state?.favorites?.length ?? 0,
    }),
    [
      state, home, rooms, playlists, results, view, setView, query, searchFilter, libraryFilter,
      selectedPlaylist, openPlaylist, theme, setTheme, accent, setAccent, normalise, setNormalise,
      toastMessage, toast, toastTone, modal, openModal, closeModal, act, play, runSearch, loadMix,
      refreshState, refreshHome, refreshRooms, attachRoom, refreshPlaylists, recent, rememberSearch,
      searching, canSearchMore, access,
      dragging, isLiked, toggleLike,
      audio, cast,
    ]
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): Store {
  const context = useContext(AppContext);
  if (!context) throw new Error("useApp must be used inside <AppProvider>");
  return context;
}
