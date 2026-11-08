/*
 * Live rooms — the Mini App following a voice chat in real time.
 *
 * The rest of the app polls. That is right for a library, a playlist or a set
 * of settings, and wrong for a player: a poll can only say where the room was
 * when the request left, so the playhead arrives already stale and has to snap
 * forward on every answer.
 *
 * This module keeps a socket open instead. Three things come down it, and each
 * has one job:
 *
 *   store   the room whenever something *changed* (track, queue, settings)
 *   clock   one timestamp a second, used only to correct a local playhead
 *   event   what just happened, for the activity line
 *
 * Between two ticks the playhead is advanced locally from `performance.now()`,
 * so the scrubber is smooth and the correction is the odd millisecond rather
 * than a visible jump. `offset` is the server/client clock difference,
 * measured with the ping/pong pair and kept at the *lowest* observed latency:
 * the fastest round trip is the one least distorted by queueing.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { ownerToken, token } from "./api";
import { telegram } from "./telegram";

export interface LiveTrack {
  id: string;
  title: string;
  uploader: string;
  duration: number;
  thumbnail: string;
  requested_by: string;
  is_video: boolean;
  source: string;
  stream: string;
  index?: number;
}

/** Every frame carries the server's clock, so the playhead can be corrected. */
interface Timed {
  server_time: number;
  position: number;
}

export interface LiveState extends Partial<Timed> {
  chat_id: number;
  track: LiveTrack | null;
  queue: LiveTrack[];
  playing: boolean;
  paused: boolean;
  has_track: boolean;
  volume: number;
  loop: string;
  autoplay: boolean;
  effects: string[];
  is_video: boolean;
  listen: number;
  streaming: boolean;
  you?: { id: number; name: string; can_control: boolean };
}

export interface LiveEvent {
  kind: "start" | "skip" | "add" | "remove" | "pause" | "resume" | "volume";
  at: number;
  track_id?: string;
  count?: number;
  volume?: number;
}

export type LiveStatus = "connecting" | "live" | "reconnecting" | "closed";

const PING_EVERY = 8000;
const POSITION_STEP = 0.05; // how often the local playhead is recomputed

/** Smallest observed round trip wins: it is the least queue-distorted sample. */
interface Sync {
  /** server_time - client_time, in seconds */
  offset: number;
  /** the position the server reported, and the client clock when it did */
  anchorPosition: number;
  anchorClient: number;
  playing: boolean;
}

function socketUrl(chatId: number): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const params = new URLSearchParams({ chat_id: String(chatId) });
  const chatToken = token();
  const owner = ownerToken();
  const initData = telegram()?.initData ?? "";
  if (chatToken) params.set("t", chatToken);
  if (owner) params.set("ot", owner);
  if (initData) params.set("init_data", initData);
  return `${scheme}://${window.location.host}/ws/room?${params.toString()}`;
}

export interface RoomClient {
  state: LiveState | null;
  status: LiveStatus;
  event: LiveEvent | null;
  /** The room clock, read on demand — never mirrored into React state. */
  position: () => number;
  control: (action: string, value?: number | string) => void;
  close: () => void;
}

/**
 * One socket, one clock, for as long as *chatId* is set.
 *
 * `control` never mutates local state. A tap is a request; the room's own state
 * message is what moves the UI, so every listener — including the one who
 * tapped — sees the change at the same moment.
 */
export function useRoomSocket(chatId: number | null, onEvent?: (event: LiveEvent) => void): RoomClient {
  const [state, setState] = useState<LiveState | null>(null);
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const [event, setEvent] = useState<LiveEvent | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const syncRef = useRef<Sync | null>(null);
  const bestRtt = useRef(Number.POSITIVE_INFINITY);
  const retryRef = useRef(0);
  const timerRef = useRef(0);
  const pingRef = useRef(0);
  const aliveRef = useRef(true);
  const eventHandler = useRef(onEvent);
  eventHandler.current = onEvent;

  useEffect(() => {
    if (chatId === null) {
      setStatus("closed");
      return;
    }
    aliveRef.current = true;

    const connect = () => {
      if (!aliveRef.current) return;
      setStatus(retryRef.current === 0 ? "connecting" : "reconnecting");
      let socket: WebSocket;
      try {
        socket = new WebSocket(socketUrl(chatId));
      } catch {
        schedule();
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        retryRef.current = 0;
        bestRtt.current = Number.POSITIVE_INFINITY;
        setStatus("live");
        pingRef.current = window.setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ t: "ping", id: Date.now() }));
          }
        }, PING_EVERY);
        socket.send(JSON.stringify({ t: "ping", id: Date.now() }));
      };

      socket.onmessage = (frame) => {
        let payload: Record<string, unknown>;
        try {
          payload = JSON.parse(String(frame.data));
        } catch {
          return;
        }
        const kind = payload.t;
        if (kind === "hello" || kind === "state") {
          const next = payload as unknown as LiveState & Timed;
          setState((previous) => ({ ...(previous ?? ({} as LiveState)), ...next }));
          anchor(next.position as number, next.server_time as number, Boolean(next.playing && !next.paused));
          if (kind === "hello" && payload.you) {
            setState((previous) => (previous ? { ...previous, you: payload.you as LiveState["you"] } : previous));
          }
        } else if (kind === "sync") {
          const beat = payload as unknown as Timed & { playing?: boolean; paused?: boolean };
          anchor(beat.position, beat.server_time, Boolean(beat.playing) && !beat.paused);
          setState((previous) =>
            previous
              ? {
                  ...previous,
                  playing: Boolean(payload.playing),
                  paused: Boolean(payload.paused),
                }
              : previous,
          );
        } else if (kind === "pong") {
          const sentAt = Number(payload.id) || 0;
          const serverTime = Number(payload.server_time) || 0;
          if (!sentAt || !serverTime) return;
          const now = Date.now();
          const rtt = now - sentAt;
          if (rtt < bestRtt.current) {
            bestRtt.current = rtt;
            const current = syncRef.current;
            syncRef.current = {
              offset: serverTime - (sentAt + rtt / 2) / 1000,
              anchorPosition: current?.anchorPosition ?? 0,
              anchorClient: current?.anchorClient ?? now,
              playing: current?.playing ?? false,
            };
          }
        } else if (kind === "event") {
          const next = payload as unknown as LiveEvent;
          setEvent(next);
          eventHandler.current?.(next);
        }
      };

      socket.onclose = () => {
        window.clearInterval(pingRef.current);
        if (!aliveRef.current) return;
        setStatus("reconnecting");
        schedule();
      };
      socket.onerror = () => socket.close();
    };

    const schedule = () => {
      if (!aliveRef.current) return;
      retryRef.current += 1;
      // 0.6 s, 1.2 s, 2.4 s … capped: a phone in a tunnel must not spam.
      const wait = Math.min(600 * 2 ** (retryRef.current - 1), 8000);
      timerRef.current = window.setTimeout(connect, wait);
    };

    connect();
    return () => {
      aliveRef.current = false;
      window.clearInterval(pingRef.current);
      window.clearTimeout(timerRef.current);
      socketRef.current?.close();
      socketRef.current = null;
      setStatus("closed");
    };
  }, [chatId]);

  const anchor = (position: number, serverTime: number, playing: boolean) => {
    const now = Date.now();
    const current = syncRef.current;
    const offset = current ? current.offset : serverTime - now / 1000;
    syncRef.current = {
      offset,
      anchorPosition: Math.max(0, Number(position) || 0),
      anchorClient: now,
      playing,
    };
  };

  return useMemo<RoomClient>(
    () => ({
      state,
      status,
      event,
      position: () => {
        const sync = syncRef.current;
        if (!sync) return 0;
        if (!sync.playing) return sync.anchorPosition;
        const elapsed = (Date.now() - sync.anchorClient) / 1000;
        const duration = state?.track?.duration ?? 0;
        const raw = sync.anchorPosition + elapsed;
        return duration > 0 ? Math.min(raw, duration) : raw;
      },
      control: (action: string, value?: number | string) => {
        const socket = socketRef.current;
        if (!socket || socket.readyState !== WebSocket.OPEN) return;
        socket.send(JSON.stringify({ t: "control", action, value }));
      },
      close: () => {
        aliveRef.current = false;
        socketRef.current?.close();
      },
    }),
    [state, status, event],
  );
}

/**
 * A clock that ticks while a room is live.
 *
 * Deliberately separate from `useRoomSocket`: the socket's state changes a few
 * times a minute, while a playhead is drawn many times a second. Subscribing
 * the whole room to that would re-render the queue, the deck and the artwork
 * for a number that only one element needs.
 */
export function useRoomClock(client: RoomClient, active: boolean): number {
  const [position, setPosition] = useState(0);
  useEffect(() => {
    if (!active) return;
    let frame = window.setInterval(() => setPosition(client.position()), POSITION_STEP * 1000);
    return () => window.clearInterval(frame);
  }, [client, active]);
  return position;
}

export { POSITION_STEP };
