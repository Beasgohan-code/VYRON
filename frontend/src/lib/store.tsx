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
import { ApiError, api, haptic, notify, setToken, telegram } from "./api";
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
  runSearch: (query: string, remember?: boolean) => Promise<void>;
  searching: boolean;
  /** "ok" · "locked" (no Telegram session) · "offline" (server unreachable) */
  access: "ok" | "locked" | "offline";
  loadMix: (key: string) => Promise<void>;
  refreshState: () => Promise<void>;
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
}

const AppContext = createContext<Store | null>(null);

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
  const [access, setAccess] = useState<"ok" | "locked" | "offline">("ok");
  const [view, setViewState] = useState<View>("home");
  const [query, setQuery] = useState("");
  const [searchFilter, setSearchFilter] = useState<SearchFilter>("all");
  const [libraryFilter, setLibraryFilter] = useState<LibraryFilter>("liked");
  const [selectedPlaylist, setSelectedPlaylist] = useState<Playlist | null>(null);
  const [theme, setThemeState] = useState<ThemeName>(() => readLocal("vyron:theme", "beat") as ThemeName);
  const [accent, setAccentState] = useState<AccentName>(() => readLocal("vyron:accent", "violet") as AccentName);
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
  }, [theme, accent]);

  const setTheme = useCallback((next: ThemeName) => {
    setThemeState(next);
    writeLocal("vyron:theme", next);
  }, []);

  const setAccent = useCallback((next: AccentName) => {
    setAccentState(next);
    writeLocal("vyron:accent", next);
  }, []);

  const setNormalise = useCallback((value: boolean) => {
    setNormaliseState(value);
    writeLocal("vyron:normalise", value ? "1" : "0");
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
    } catch (error) {
      if (error instanceof ApiError) {
        setAccess(error.status === 401 ? "locked" : "offline");
        if (error.status !== 401) toast(error.message, "error");
      } else {
        setAccess("offline");
      }
    }
  }, [toast]);

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
    const boot = async () => {
      const tg = telegram();
      tg?.ready?.();
      tg?.expand?.();
      try {
        tg?.setHeaderColor?.("#08080e");
        tg?.setBackgroundColor?.("#08080e");
      } catch {
        /* older clients */
      }
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
  }, [refreshState, refreshRooms, refreshPlaylists]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refreshState();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [refreshState]);

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

  const rememberSearch = useCallback((term: string) => {
    setRecent((previous) => {
      const next = [term, ...previous.filter((item) => item !== term)].slice(0, 8);
      writeLocal("vyron:recent", JSON.stringify(next));
      return next;
    });
  }, []);

  const searchSeq = useRef(0);

  const runSearch = useCallback(
    async (value: string, remember = true) => {
      const clean = value.trim();
      if (!clean) return;
      setQuery(clean);
      if (remember) rememberSearch(clean);
      const seq = (searchSeq.current += 1);
      setSearching(true);
      try {
        const payload = await api.search(clean);
        if (seq === searchSeq.current) setResults(payload.results ?? []);
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

  const value = useMemo<Store>(
    () => ({
      state,
      home,
      rooms,
      playlists,
      results,
      searching,
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
      refreshRooms,
      attachRoom,
      refreshPlaylists,
      recent,
      rememberSearch,
      audio,
      cast,
      dragging,
      setDragging,
    }),
    [
      state, home, rooms, playlists, results, view, setView, query, searchFilter, libraryFilter,
      selectedPlaylist, openPlaylist, theme, setTheme, accent, setAccent, normalise, setNormalise,
      toastMessage, toast, toastTone, modal, openModal, closeModal, act, play, runSearch, loadMix,
      refreshState, refreshRooms, attachRoom, refreshPlaylists, recent, rememberSearch, searching, access,
      dragging,
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
