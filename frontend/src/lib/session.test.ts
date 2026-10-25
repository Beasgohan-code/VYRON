import { describe, expect, it } from "vitest";
import {
  SESSION_KEY,
  SESSION_VERSION,
  buildSession,
  clearSession,
  describeSession,
  parseSession,
  readSession,
  upNext,
  writeSession,
} from "./session";

const track = (id: string, duration = 200) => ({ id, title: `T${id}`, duration, uploader: "A" });
const memory = () => {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
    dump: data,
  };
};

describe("playback session", () => {
  it("captures the queue, the index and the position", () => {
    const session = buildSession({
      queue: [track("a"), track("b")],
      track: { id: "b", title: "Tb" },
      position: 31.6,
      rate: 1.25,
      volume: 0.4,
      repeat: "all",
    });
    expect(session).not.toBeNull();
    expect(session!.index).toBe(1);
    expect(session!.position).toBeCloseTo(31.6);
    expect(session!.repeat).toBe("all");
    expect(describeSession(session!)).toBe("2 of 2 · 0:31 in");
  });

  it("clamps a position past the end of the track", () => {
    const session = buildSession({ queue: [track("a", 100)], track: track("a"), position: 9999 })!;
    expect(session.position).toBe(100);
  });

  it("refuses to save an empty queue", () => {
    expect(buildSession({ queue: [] })).toBeNull();
    expect(buildSession({ queue: [{ title: "no id" }] })).toBeNull();
  });

  it("round-trips through storage", () => {
    const store = memory();
    const session = buildSession({ queue: [track("a")], track: track("a"), position: 12 })!;
    writeSession(session, store);
    const read = readSession(store);
    expect(read?.queue[0].id).toBe("a");
    expect(read?.position).toBe(12);
    clearSession(store);
    expect(readSession(store)).toBeNull();
  });

  it("rejects a session from another version, or a broken one", () => {
    expect(parseSession("not json")).toBeNull();
    expect(parseSession(JSON.stringify({ version: 1, queue: [track("a")] }))).toBeNull();
    expect(parseSession(JSON.stringify({ version: SESSION_VERSION, queue: [] }))).toBeNull();
    expect(
      parseSession(JSON.stringify({ version: SESSION_VERSION, queue: [track("a")], savedAt: 0 }))
    ).toBeNull();
  });

  it("forgets a session older than a month", () => {
    const now = Date.now();
    const old = JSON.stringify({
      version: SESSION_VERSION,
      queue: [track("a")],
      savedAt: now - 31 * 24 * 60 * 60 * 1000,
    });
    expect(parseSession(old, now)).toBeNull();
  });

  it("repairs an out-of-range index instead of throwing", () => {
    const raw = JSON.stringify({
      version: SESSION_VERSION,
      queue: [track("a"), track("b")],
      index: 99,
      position: 5,
      savedAt: Date.now(),
    });
    const session = parseSession(raw)!;
    expect(session.index).toBe(1);
    expect(upNext(session)).toBeUndefined();
  });

  it("reads null when storage itself throws", () => {
    const broken = {
      getItem: () => {
        throw new Error("denied");
      },
    };
    expect(readSession(broken as unknown as Storage)).toBeNull();
    expect(SESSION_KEY).toBe("vyron:session");
  });
});
