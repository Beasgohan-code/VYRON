import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Code2,
  Command,
  Compass,
  Disc3,
  Download,
  Headphones,
  Heart,
  Home,
  Library,
  ListMusic,
  ListPlus,
  Maximize2,
  Mic2,
  Pause,
  Play,
  Repeat,
  Search,
  Settings,
  Shuffle,
  SkipBack,
  SkipForward,
  Users,
  VolumeX,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { reveal } from "../lib/anim";
import { useApp } from "../lib/store";
import type { View } from "../lib/types";

interface Item {
  id: string;
  label: string;
  hint?: string;
  group: "Go to" | "Playback" | "Actions";
  icon: typeof Home;
  keys?: string;
  run: () => void;
}

const VIEWS: { view: View; label: string; icon: typeof Home }[] = [
  { view: "home", label: "Home", icon: Home },
  { view: "search", label: "Search", icon: Search },
  { view: "library", label: "Library", icon: Library },
  { view: "queue", label: "Queue", icon: ListMusic },
  { view: "playlists", label: "Playlists", icon: Disc3 },
  { view: "rooms", label: "Listen together", icon: Users },
  { view: "api", label: "Music API", icon: Code2 },
  { view: "profile", label: "Settings", icon: Settings },
];

/** ⌘K / Ctrl+K command palette — navigation, playback and quick actions. */
export function CommandPalette() {
  const { audio, setView, act, openModal, toast, state, runSearch } = useApp();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
        return;
      }
      if (!typing && (event.key === "?" || (event.shiftKey && event.key === "/"))) {
        event.preventDefault();
        setOpen(true);
      }
      if (event.key === "Escape" && open) {
        event.preventDefault();
        setOpen(false);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("vyron:palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("vyron:palette", onOpen);
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setCursor(0);
      return;
    }
    const id = window.setTimeout(() => {
      inputRef.current?.focus();
      const panel = document.querySelector(".palette");
      if (panel) reveal(panel.querySelectorAll(".palette-item, .palette-group"), { y: 10, delay: 16, duration: 320 });
    }, 30);
    return () => window.clearTimeout(id);
  }, [open]);

  const close = () => setOpen(false);
  const go = (view: View) => {
    setView(view);
    close();
  };

  const items = useMemo<Item[]>(() => {
    const playing = audio.playing;
    const current = audio.track ?? state?.now;
    return [
      ...VIEWS.map(({ view, label, icon }) => ({
        id: `go:${view}`,
        label,
        hint: view === "api" ? "keys, docs, endpoints" : undefined,
        group: "Go to" as const,
        icon,
        run: () => go(view),
      })),
      {
        id: "play:toggle",
        label: playing ? "Pause" : "Play",
        hint: current?.title,
        group: "Playback",
        icon: playing ? Pause : Play,
        keys: "space",
        run: () => {
          audio.toggle();
          close();
        },
      },
      {
        id: "play:next",
        label: "Next track",
        group: "Playback",
        icon: SkipForward,
        keys: "n",
        run: () => {
          audio.next();
          close();
        },
      },
      {
        id: "play:prev",
        label: "Previous track",
        group: "Playback",
        icon: SkipBack,
        run: () => {
          audio.prev();
          close();
        },
      },
      {
        id: "play:seekf",
        label: "Seek forward 10s",
        group: "Playback",
        icon: ArrowRight,
        keys: "→",
        run: () => {
          audio.seekBy(10);
          close();
        },
      },
      {
        id: "play:seekb",
        label: "Seek back 10s",
        group: "Playback",
        icon: ArrowLeft,
        keys: "←",
        run: () => {
          audio.seekBy(-10);
          close();
        },
      },
      {
        id: "play:mute",
        label: audio.muted ? "Unmute" : "Mute",
        group: "Playback",
        icon: VolumeX,
        keys: "m",
        run: () => {
          audio.toggleMute();
          close();
        },
      },
      {
        id: "play:shuffle",
        label: audio.shuffle ? "Shuffle: on" : "Shuffle: off",
        group: "Playback",
        icon: Shuffle,
        run: () => {
          audio.toggleShuffle();
          close();
        },
      },
      {
        id: "play:repeat",
        label: `Repeat: ${audio.repeat}`,
        group: "Playback",
        icon: Repeat,
        run: () => {
          audio.cycleRepeat();
          close();
        },
      },
      {
        id: "act:expand",
        label: "Open full player",
        group: "Actions",
        icon: Maximize2,
        run: () => {
          if (audio.track) audio.setExpanded(true);
          else toast("Nothing is playing in the app yet", "info");
          close();
        },
      },
      {
        id: "act:lyrics",
        label: "Lyrics of this track",
        group: "Actions",
        icon: Mic2,
        run: () => {
          if (audio.track) audio.setExpanded(true);
          close();
        },
      },
      {
        id: "act:download",
        label: "Download music",
        group: "Actions",
        icon: Download,
        run: () => {
          openModal({ type: "download" });
          close();
        },
      },
      {
        id: "act:playlist",
        label: "Create playlist",
        group: "Actions",
        icon: ListPlus,
        run: () => {
          openModal({ type: "new-playlist" });
          close();
        },
      },
      {
        id: "act:favorite",
        label: "Save current track",
        group: "Actions",
        icon: Heart,
        run: () => {
          void act("favorite").then((payload) =>
            toast(payload ? "Saved to liked songs" : "Could not save that", payload ? "success" : "error")
          );
          close();
        },
      },
      {
        id: "act:now",
        label: "Play in the voice chat",
        group: "Actions",
        icon: Headphones,
        run: () => {
          go("queue");
        },
      },
      {
        id: "act:rooms",
        label: "Browse live rooms",
        group: "Actions",
        icon: Compass,
        run: () => go("rooms"),
      },
    ];
  }, [act, audio, openModal, runSearch, state, toast]);

  const needle = query.trim().toLowerCase();
  const filtered = needle
    ? items.filter(
        (item) =>
          item.label.toLowerCase().includes(needle) ||
          (item.hint ?? "").toLowerCase().includes(needle) ||
          item.group.toLowerCase().includes(needle)
      )
    : items;

  const searchItem: Item | null =
    needle.length > 1
      ? {
          id: "act:search",
          label: `Search “${query.trim()}”`,
          hint: "find it on YouTube and play it here",
          group: "Actions",
          icon: Search,
          run: () => {
            void runSearch(query.trim());
            go("search");
          },
        }
      : null;

  const list = searchItem ? [searchItem, ...filtered] : filtered;
  const index = Math.min(cursor, Math.max(0, list.length - 1));

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((value) => Math.min(value + 1, list.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((value) => Math.max(value - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      list[index]?.run();
    }
  };

  if (!open) return null;

  let lastGroup = "";
  return (
    <div className="palette-backdrop" role="presentation" onMouseDown={close}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="palette-input">
          <Search size={17} />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setCursor(0);
            }}
            onKeyDown={onKeyDown}
            placeholder="Jump to a view, control playback, search…"
            aria-label="Search commands"
          />
          <kbd>esc</kbd>
        </div>

        <div className="palette-list" role="listbox" aria-label="Commands">
          {list.length === 0 && <p className="empty-state">No command matches that.</p>}
          {list.map((item, position) => {
            const Icon = item.icon;
            const header = item.group !== lastGroup ? item.group : "";
            lastGroup = item.group;
            return (
              <div key={item.id}>
                {header && <span className="palette-group">{header}</span>}
                <button
                  type="button"
                  role="option"
                  aria-selected={position === index}
                  className={`palette-item ${position === index ? "active" : ""}`}
                  onMouseEnter={() => setCursor(position)}
                  onClick={item.run}
                >
                  <span className="pi-icon">
                    <Icon size={15} />
                  </span>
                  <span className="pi-label">{item.label}</span>
                  {item.hint && <span className="pi-hint">{item.hint}</span>}
                  {item.keys && <kbd>{item.keys}</kbd>}
                </button>
              </div>
            );
          })}
        </div>

        <div className="palette-foot">
          <span>
            <kbd>
              <ArrowUp size={10} />
            </kbd>
            <kbd>
              <ArrowDown size={10} />
            </kbd>
            to move
          </span>
          <span>
            <kbd>↵</kbd> to run
          </span>
          <span className="palette-brand">
            <Command size={11} /> K
          </span>
        </div>
      </div>
    </div>
  );
}
