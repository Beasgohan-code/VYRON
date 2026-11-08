import {
  ArrowLeft,
  AudioLines,
  CircleSlash,
  Loader2,
  Mic2,
  Pause,
  Play,
  Radio,
  Repeat,
  Repeat1,
  ShieldCheck,
  Shuffle,
  SkipForward,
  Square,
  Users,
  Volume1,
  Volume2,
  VolumeX,
  Waves,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Cover } from "../components/Cover";
import { RoomLyrics } from "../components/RoomLyrics";
import { Seek } from "../components/Seek";
import { streamUrl } from "../lib/audio";
import { useApp } from "../lib/store";
import { fmtDuration } from "../lib/format";
import { haptic } from "../lib/telegram";
import { type LiveEvent, type LiveTrack, useRoomClock, useRoomSocket } from "../lib/live";
import type { Room as RoomSummary } from "../lib/types";

interface Props {
  room: RoomSummary;
  onClose: () => void;
}

/** The last few things that happened, kept short enough to read at a glance. */
const ACTIVITY = 3;

function eventLine(event: LiveEvent, title: string): string {
  switch (event.kind) {
    case "start":
      return `Started ${title || "the room"}`;
    case "skip":
      return `Now playing ${title || "the next track"}`;
    case "add":
      return `${event.count ?? 1} track${(event.count ?? 1) === 1 ? "" : "s"} added`;
    case "remove":
      return `${event.count ?? 1} track${(event.count ?? 1) === 1 ? "" : "s"} removed`;
    case "pause":
      return "Paused the room";
    case "resume":
      return "Back on";
    case "volume":
      return `Volume ${event.volume ?? 0}%`;
    default:
      return "";
  }
}

function loopGlyph(loop: string) {
  if (loop === "one") return <Repeat1 size={17} />;
  return <Repeat size={17} />;
}

/**
 * A voice chat, as a player.
 *
 * The screen follows the room over `/ws/room` rather than polling it: the
 * playhead is advanced locally and corrected by a timestamped tick, so it moves
 * continuously instead of stepping every few seconds. Every control here is a
 * *request* — the room answers with its own state, and this screen renders that
 * answer, which is why two people tapping at once cannot disagree about what is
 * playing.
 */
export function RoomScreen({ room, onClose }: Props) {
  const { toast, attachRoom, state: app } = useApp();
  const [attachVersion, setAttachVersion] = useState(0);
  return (
    <RoomBody
      key={attachVersion}
      room={room}
      onClose={onClose}
      onTakeControl={async () => {
        if (await attachRoom(room.chat_id)) setAttachVersion((value) => value + 1);
      }}
      controlling={Boolean(app?.chat?.id && app.chat.id === room.chat_id)}
      toast={toast}
    />
  );
}

function RoomBody({
  room,
  onClose,
  onTakeControl,
  controlling,
  toast,
}: Props & {
  onTakeControl: () => Promise<void>;
  controlling: boolean;
  toast: (message: string, tone?: "info" | "error" | "success") => void;
}) {
  const [activity, setActivity] = useState<LiveEvent[]>([]);
  const [deck, setDeck] = useState<"queue" | "lyrics" | "people">("queue");
  const [pendingSeek, setPendingSeek] = useState<number | null>(null);
  const [listenAlong, setListenAlong] = useState(() => {
    try {
      return localStorage.getItem("vyron:roomListen") === "1";
    } catch {
      return false;
    }
  });

  const onEvent = useCallback((event: LiveEvent) => {
    setActivity((previous) => [event, ...previous].slice(0, ACTIVITY));
  }, []);
  const client = useRoomSocket(room.chat_id, onEvent);
  const live = client.state;
  const track = live?.track ?? null;
  const playing = Boolean(live?.playing) && !live?.paused;

  /* The playhead is drawn from the local clock, twenty times a second. Only this
     value lives on that cadence — the queue and the decks do not. */
  const clock = useRoomClock(client, Boolean(track));
  const position = pendingSeek ?? clock;
  const duration = track?.duration ?? 0;

  /* A seek is optimistic for exactly as long as its round trip: holding the
     requested second keeps the thumb where the finger left it instead of
     snapping back for a tick. */
  useEffect(() => {
    if (pendingSeek === null) return;
    const clear = window.setTimeout(() => setPendingSeek(null), 1400);
    return () => window.clearTimeout(clear);
  }, [pendingSeek]);

  const control = useCallback(
    (action: string, value?: number | string) => {
      haptic("light");
      client.control(action, value);
    },
    [client]
  );

  /* ── listen along ───────────────────────────────────────────────────────
     The bot streams into the voice chat; this plays the same bytes here so a
     listener can hear the room without unmuting a call. It follows the room's
     clock: when the two drift more than a second and a half it is nudged back,
     rather than re-seeking on every tick (which would stutter). */
  const audio = useRef<HTMLAudioElement | null>(null);
  useEffect(() => {
    try {
      localStorage.setItem("vyron:roomListen", listenAlong ? "1" : "0");
    } catch {
      /* private mode */
    }
  }, [listenAlong]);

  useEffect(() => {
    const element = audio.current;
    if (!element || !listenAlong || !track) return;
    const target = streamUrl({ id: track.id, title: track.title });
    if (element.getAttribute("src") !== target) element.setAttribute("src", target);
    if (playing) void element.play().catch(() => setListenAlong(false));
    else element.pause();
  }, [listenAlong, track, playing]);

  useEffect(() => {
    const element = audio.current;
    if (!element || !listenAlong || !playing) return;
    const timer = window.setInterval(() => {
      const drift = element.currentTime - client.position();
      if (Math.abs(drift) > 1.5) element.currentTime = Math.max(0, client.position() + 0.12);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [client, listenAlong, playing]);

  /* ── a measured stage ───────────────────────────────────────────────────
     Playeon measures its header instead of guessing a height: the stage is then
     exactly the space that is left, on every phone, in either orientation. */
  const root = useRef<HTMLDivElement>(null);
  const head = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = root.current;
    const bar = head.current;
    if (!node || !bar) return;
    const observer = new ResizeObserver(() => {
      node.style.setProperty("--lr-head", `${bar.getBoundingClientRect().height}px`);
    });
    observer.observe(bar);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === " ") {
        event.preventDefault();
        control(playing ? "pause" : "resume");
      }
      if (event.key === "ArrowRight" && duration) setPendingSeek(Math.min(duration, position + 10));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [control, duration, onClose, playing, position]);

  const lines = useMemo(
    () => activity.map((event) => eventLine(event, track?.title ?? "")).filter(Boolean),
    [activity, track?.title]
  );

  const shape = track?.is_video ? "wide" : "square";
  const canControl = Boolean(live?.you?.can_control);

  return (
    <div className={`live-room ${playing ? "playing" : ""}`} ref={root} role="dialog" aria-modal="true" aria-label={`${room.title} player`}>
      <div className="lr-glow" aria-hidden="true" />
      {track ? (
        <div className="lr-backdrop" aria-hidden="true">
          <Cover track={track} width={600} />
        </div>
      ) : null}

      <div className="lr-head" ref={head}>
        <button type="button" className="lr-back" onClick={onClose} aria-label="Back to rooms">
          <ArrowLeft size={18} />
        </button>
        <div className="lr-where">
          <b>{room.title}</b>
          <span>
            {playing ? (
              <>
                <i className="lr-pulse" aria-hidden="true" /> live · {live?.listen ?? 0} listening
              </>
            ) : live?.paused ? (
              "paused"
            ) : (
              "quiet"
            )}
          </span>
        </div>
        <div className="lr-head-actions">
          {canControl ? (
            <span className="lr-badge" title="You can control this room">
              <ShieldCheck size={13} /> control
            </span>
          ) : (
            <button type="button" className="btn btn-ghost sm" onClick={() => void onTakeControl()}>
              {controlling ? "Reconnect" : "Take control"}
            </button>
          )}
        </div>
      </div>

      <div className="lr-body" data-shape={shape}>
        {client.status !== "live" && !track ? (
          <div className="lr-state">
            <Loader2 className="spin" size={22} />
            <b>{client.status === "reconnecting" ? "Reconnecting…" : "Opening the room…"}</b>
          </div>
        ) : !track ? (
          <div className="lr-state">
            <span className="empty-icon">
              <CircleSlash size={20} />
            </span>
            <b>This room is quiet</b>
            <p>
              Send <code>/play</code> in the chat and the bot joins the voice chat. Whatever it
              plays shows up here, live.
            </p>
          </div>
        ) : (
          <>
            <div className="lr-stage" data-shape={shape}>
              <div className="lr-art">
                <Cover track={track} width={600} />
                {playing ? <span className="lr-eq" aria-hidden="true"><i /><i /><i /><i /></span> : null}
              </div>
              {track.is_video ? <span className="lr-chip">video</span> : null}
              {listenAlong && track ? <audio ref={audio} preload="auto" /> : null}
            </div>

            <div className="lr-titles">
              <b title={track.title}>{track.title}</b>
              <span>
                {[track.uploader, track.requested_by && `asked by ${track.requested_by}`]
                  .filter(Boolean)
                  .join(" · ") || "playing in the voice chat"}
              </span>
            </div>

            <div className="lr-seek">
              <Seek
                seed={track.id || track.title}
                position={position}
                duration={duration}
                playing={playing}
                onSeek={(seconds) => {
                  setPendingSeek(seconds);
                  control("seek", Math.round(seconds));
                }}
              />
              <div className="lr-times">
                <span>{fmtDuration(position)}</span>
                <span>{duration ? `-${fmtDuration(Math.max(0, duration - position))}` : "--:--"}</span>
              </div>
            </div>

            <div className="lr-controls">
              <button
                type="button"
                className={`lr-btn ${live?.loop && live.loop !== "off" ? "on" : ""}`}
                onClick={() => control("loop")}
                aria-label={`Loop ${live?.loop ?? "off"}`}
                title={`Loop ${live?.loop ?? "off"}`}
              >
                {loopGlyph(live?.loop ?? "off")}
              </button>
              <button type="button" className="lr-btn" onClick={() => control("volume", Math.max(1, (live?.volume ?? 100) - 10))} aria-label="Quieter">
                {volumeGlyph(live?.volume ?? 100, -1)}
              </button>
              <button
                type="button"
                className={`lr-play ${client.status === "reconnecting" ? "stale" : ""}`}
                onClick={() => control(playing ? "pause" : "resume")}
                aria-label={playing ? "Pause" : "Play"}
                disabled={!canControl}
              >
                {playing ? <Pause size={24} /> : <Play size={24} />}
              </button>
              <button type="button" className="lr-btn" onClick={() => control("volume", Math.min(200, (live?.volume ?? 100) + 10))} aria-label="Louder">
                {volumeGlyph(live?.volume ?? 100, 1)}
              </button>
              <button type="button" className="lr-btn" onClick={() => control("skip")} aria-label="Skip" disabled={!canControl}>
                <SkipForward size={19} />
              </button>
            </div>

            <div className="lr-under">
              <span className="lr-vol">
                {volumeIcon(live?.volume ?? 100)} {live?.volume ?? 100}%
              </span>
              <button type="button" className={`lr-link ${live?.autoplay ? "on" : ""}`} onClick={() => control("autoplay")}>
                <Radio size={13} /> radio {live?.autoplay ? "on" : "off"}
              </button>
              <button type="button" className={`lr-link ${live?.effects?.length ? "on" : ""}`} onClick={() => control("effects", "bassboost")}>
                <Waves size={13} /> {live?.effects?.length ? live.effects.join(", ") : "effects"}
              </button>
              <button
                type="button"
                className={`lr-link ${listenAlong ? "on" : ""}`}
                onClick={() => {
                  haptic("light");
                  setListenAlong((value) => !value);
                }}
              >
                <AudioLines size={13} /> listen here
              </button>
            </div>

            <div className="lr-decks">
              <div className="lr-tabs" role="tablist">
                <button
                  type="button"
                  role="tab"
                  aria-selected={deck === "queue"}
                  className={deck === "queue" ? "on" : ""}
                  onClick={() => setDeck("queue")}
                >
                  Up next {live?.queue?.length ? <em>{live.queue.length}</em> : null}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={deck === "lyrics"}
                  className={deck === "lyrics" ? "on" : ""}
                  onClick={() => setDeck("lyrics")}
                >
                  <Mic2 size={12} /> Lyrics
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={deck === "people"}
                  className={deck === "people" ? "on" : ""}
                  onClick={() => setDeck("people")}
                >
                  <Users size={12} /> {live?.listen ?? 0} listening
                </button>
              </div>

              {deck === "queue" ? (
                live?.queue?.length ? (
                  <ol className="lr-queue">
                    {live.queue.map((item) => (
                      <QueueRow key={`${item.id}-${item.index}`} track={item} />
                    ))}
                  </ol>
                ) : (
                  <p className="lr-hint">
                    Nothing after this one. Add songs with <code>/play</code> in the chat — they
                    appear here as soon as they are queued.
                  </p>
                )
              ) : deck === "lyrics" && track ? (
                <RoomLyrics
                  title={track.title}
                  artist={track.uploader}
                  duration={track.duration}
                  position={position}
                  playing={playing}
                  onSeek={canControl ? (seconds) => {
                    setPendingSeek(seconds);
                    control("seek", Math.round(seconds));
                  } : undefined}
                />
              ) : (
                <div className="lr-people">
                  <div className="lr-count">
                    <Users size={16} />
                    <b>{live?.listen ?? 0}</b>
                    <span>in the voice chat</span>
                  </div>
                  <dl className="lr-facts">
                    <div>
                      <dt>volume</dt>
                      <dd>{live?.volume ?? 100}%</dd>
                    </div>
                    <div>
                      <dt>loop</dt>
                      <dd>{live?.loop ?? "off"}</dd>
                    </div>
                    <div>
                      <dt>radio</dt>
                      <dd>{live?.autoplay ? "on" : "off"}</dd>
                    </div>
                    <div>
                      <dt>streaming</dt>
                      <dd>{live?.streaming ? "ready" : "not ready"}</dd>
                    </div>
                  </dl>
                  <p className="lr-hint">
                    Everyone in this app sees the same track, the same second and the same
                    volume — taps go through the room, not through this phone.
                  </p>
                </div>
              )}
            </div>

            <div className="lr-activity" aria-live="polite">
              {lines.length ? (
                lines.map((line, index) => (
                  <span key={`${line}-${index}`} className={index === 0 ? "fresh" : ""}>
                    {line}
                  </span>
                ))
              ) : (
                <span>Watching this room live.</span>
              )}
            </div>
          </>
        )}
      </div>

      <div className="lr-foot">
        <button type="button" className="lr-danger" onClick={() => control("stop")} disabled={!canControl || !track}>
          <Square size={13} /> Stop the room
        </button>
        <button
          type="button"
          className="lr-danger ghost"
          onClick={() => control("clear")}
          disabled={!canControl || !live?.queue?.length}
        >
          Clear queue
        </button>
        <button
          type="button"
          className="lr-danger ghost"
          onClick={() => {
            control("shuffle");
            toast("Shuffled by the room", "info");
          }}
          disabled={!canControl || (live?.queue?.length ?? 0) < 2}
        >
          <Shuffle size={13} /> Shuffle
        </button>
      </div>
    </div>
  );
}

function QueueRow({ track }: { track: LiveTrack }) {
  return (
    <li className="lr-row">
      <span className="lr-row-index">{track.index ?? "·"}</span>
      <span className="lr-row-art">
        <Cover track={track} width={96} rounded={8} />
      </span>
      <span className="lr-row-text">
        <b>{track.title}</b>
        <span>{[track.uploader, track.requested_by && `· ${track.requested_by}`].filter(Boolean).join(" ")}</span>
      </span>
      <span className="lr-row-time">{track.duration ? fmtDuration(track.duration) : ""}</span>
    </li>
  );
}

function volumeIcon(volume: number, direction = 0) {
  if (direction < 0 && volume <= 30) return <Volume1 size={18} />;
  if (direction > 0 && volume >= 80) return <Volume2 size={18} />;
  if (volume <= 1) return <VolumeX size={18} />;
  return volume >= 55 ? <Volume2 size={18} /> : <Volume1 size={18} />;
}

function volumeGlyph(volume: number, direction: number) {
  return direction < 0 ? volumeIcon(Math.max(1, volume - 10)) : volumeIcon(volume);
}
