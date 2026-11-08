import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRoomSocket } from "./live";

/**
 * The parts of a WebSocket this client uses, under our control.
 *
 * A real one cannot be told "now a state message arrives", which is the only
 * interesting moment in this module: what happens between two messages is the
 * whole design.
 */
class FakeSocket {
  static all: FakeSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((frame: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeSocket.all.push(this);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }

  /* ── the test's side of the wire ── */
  open() {
    this.readyState = 1;
    this.onopen?.();
  }

  deliver(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

const T0 = 1_760_000_000_000; // a fixed wall clock, in ms

const hello = {
  t: "hello",
  chat_id: -100,
  server_time: T0 / 1000,
  position: 42,
  playing: true,
  paused: false,
  has_track: true,
  track: { id: "yt1", title: "Kesariya", duration: 268 },
  queue: [{ id: "yt2", title: "Tum Hi Ho" }],
  volume: 80,
  loop: "off",
  autoplay: false,
  effects: [],
  is_video: false,
  listen: 3,
  streaming: true,
  you: { id: 7, name: "Asha", can_control: true },
};

function sentMessages(socket: FakeSocket): Record<string, unknown>[] {
  return socket.sent.map((payload) => JSON.parse(payload) as Record<string, unknown>);
}

describe("the live room socket", () => {
  beforeEach(() => {
    FakeSocket.all = [];
    vi.useFakeTimers();
    vi.setSystemTime(T0);
    vi.stubGlobal("WebSocket", FakeSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("asks for the room it was given, and nothing else", () => {
    renderHook(() => useRoomSocket(-100));
    expect(FakeSocket.all).toHaveLength(1);
    expect(FakeSocket.all[0].url).toContain("/ws/room?");
    expect(FakeSocket.all[0].url).toContain("chat_id=-100");
  });

  it("turns the first frame into the room the screen draws", () => {
    const { result } = renderHook(() => useRoomSocket(-100));
    act(() => {
      FakeSocket.all[0].open();
      FakeSocket.all[0].deliver(hello);
    });

    expect(result.current.status).toBe("live");
    expect(result.current.state?.track?.title).toBe("Kesariya");
    expect(result.current.state?.queue).toHaveLength(1);
    expect(result.current.state?.you?.can_control).toBe(true);
    expect(result.current.state?.listen).toBe(3);
  });

  it("advances the playhead itself between two ticks", () => {
    const { result } = renderHook(() => useRoomSocket(-100));
    act(() => {
      FakeSocket.all[0].open();
      FakeSocket.all[0].deliver(hello);
    });
    const start = result.current.position();

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    // Three seconds pass with no message at all: the clock still moves, because
    // the last tick said "playing at 42 s, at this server time".
    expect(result.current.position() - start).toBeGreaterThan(2.5);
    expect(result.current.position() - start).toBeLessThan(3.5);
  });

  it("stands still while the room is paused", () => {
    const { result } = renderHook(() => useRoomSocket(-100));
    act(() => {
      FakeSocket.all[0].open();
      FakeSocket.all[0].deliver({ ...hello, playing: false, paused: true });
    });
    const paused = result.current.position();
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current.position()).toBeCloseTo(paused, 1);
  });

  it("never draws past the end of the track", () => {
    const { result } = renderHook(() => useRoomSocket(-100));
    act(() => {
      FakeSocket.all[0].open();
      FakeSocket.all[0].deliver({ ...hello, position: 267 });
    });
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(result.current.position()).toBe(268);
  });

  it("sends a tap as a request, and leaves the state alone until the room answers", () => {
    const { result } = renderHook(() => useRoomSocket(-100));
    act(() => {
      FakeSocket.all[0].open();
      FakeSocket.all[0].deliver(hello);
    });
    const before = result.current.state;

    act(() => {
      result.current.control("pause");
      result.current.control("volume", 55);
    });

    const sent = sentMessages(FakeSocket.all[0]);
    expect(sent).toContainEqual({ t: "control", action: "pause" });
    expect(sent).toContainEqual({ t: "control", action: "volume", value: 55 });
    // Optimism here would mean two listeners seeing different rooms for a second.
    expect(result.current.state).toBe(before);
  });

  it("corrects its clock from a pong instead of trusting the phone", () => {
    const { result } = renderHook(() => useRoomSocket(-100));
    act(() => {
      FakeSocket.all[0].open();
      FakeSocket.all[0].deliver(hello);
    });
    const ping = sentMessages(FakeSocket.all[0]).find((message) => message.t === "ping");
    expect(ping).toBeDefined();

    act(() => {
      // The server's clock is 2 s ahead of ours; the answer takes 200 ms.
      vi.setSystemTime(T0 + 200);
      FakeSocket.all[0].deliver({
        t: "pong",
        id: ping?.id,
        server_time: (T0 + 200) / 1000 + 2,
      });
      FakeSocket.all[0].deliver({ t: "sync", position: 50, playing: true, paused: false, server_time: (T0 + 200) / 1000 + 2 });
    });

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    const reported = result.current.position();
    expect(reported).toBeGreaterThan(51);
    expect(reported).toBeLessThan(53);
  });

  it("hands an event to the screen that asked for it", () => {
    const seen: string[] = [];
    renderHook(() => useRoomSocket(-100, (event) => seen.push(event.kind)));
    act(() => {
      FakeSocket.all[0].open();
      FakeSocket.all[0].deliver(hello);
      FakeSocket.all[0].deliver({ t: "event", kind: "skip", at: 1, track_id: "yt9" });
    });
    expect(seen).toEqual(["skip"]);
  });

  it("reconnects after a dropped socket, backing off instead of hammering", () => {
    renderHook(() => useRoomSocket(-100));
    act(() => {
      FakeSocket.all[0].open();
      FakeSocket.all[0].deliver(hello);
      FakeSocket.all[0].close();
    });
    expect(FakeSocket.all).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(700);
    });
    expect(FakeSocket.all).toHaveLength(2);

    act(() => {
      FakeSocket.all[1].close();
      vi.advanceTimersByTime(700); // too soon for the second attempt
    });
    expect(FakeSocket.all).toHaveLength(2);

    act(() => {
      vi.advanceTimersByTime(800);
    });
    expect(FakeSocket.all).toHaveLength(3);
  });

  it("does not reconnect once the screen is closed", () => {
    const { unmount } = renderHook(() => useRoomSocket(-100));
    act(() => {
      FakeSocket.all[0].open();
    });
    unmount();
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    expect(FakeSocket.all).toHaveLength(1);
  });

  it("opens nothing when it is not asked for a room", () => {
    const { result } = renderHook(() => useRoomSocket(null));
    expect(FakeSocket.all).toHaveLength(0);
    expect(result.current.status).toBe("closed");
  });
});
