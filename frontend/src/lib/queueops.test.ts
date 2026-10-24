import { describe, expect, it } from "vitest";
import { enqueue, indexOf, keyOf, move, nextIndex, removeAt, shuffled, totalDuration } from "./queueops";
import type { Track } from "./types";

const track = (id: string): Track => ({ id, title: `Track ${id}`, duration: 100 });

describe("queue arithmetic", () => {
  const queue = [track("a"), track("b"), track("c")];

  it("identifies tracks by id, falling back to the title", () => {
    expect(keyOf(track("a"))).toBe("a");
    expect(keyOf({ title: "No id" })).toBe("No id");
    expect(keyOf(null)).toBe("");
    expect(indexOf(queue, track("b"))).toBe(1);
    expect(indexOf(queue, track("z"))).toBe(-1);
  });

  it("never queues the same track twice", () => {
    expect(enqueue(queue, track("a"))).toBe(queue);
    expect(enqueue(queue, track("d")).map(keyOf)).toEqual(["a", "b", "c", "d"]);
  });

  it("inserts a play-next track directly after the current one", () => {
    expect(enqueue(queue, track("d"), { next: true, current: track("a") }).map(keyOf)).toEqual([
      "a", "d", "b", "c",
    ]);
    // Current track not in the list: play-next still has to land somewhere sane.
    expect(enqueue(queue, track("d"), { next: true, current: track("z") }).map(keyOf)).toEqual([
      "a", "b", "c", "d",
    ]);
  });

  it("removes and moves without touching the original array", () => {
    const removed = removeAt(queue, 1);
    expect(removed.map(keyOf)).toEqual(["a", "c"]);
    expect(queue.map(keyOf)).toEqual(["a", "b", "c"]);
    expect(removeAt(queue, 9)).toBe(queue);

    expect(move(queue, 2, 0).map(keyOf)).toEqual(["c", "a", "b"]);
    expect(move(queue, 0, 2).map(keyOf)).toEqual(["b", "c", "a"]);
    expect(move(queue, 1, 1)).toBe(queue);
    expect(move(queue, -1, 0)).toBe(queue);
  });

  it("knows which index comes next, including at the end", () => {
    expect(nextIndex(queue, track("a"))).toBe(1);
    expect(nextIndex(queue, track("c"))).toBeNull();
    expect(nextIndex(queue, track("c"), { repeat: "all" })).toBe(0);
    expect(nextIndex(queue, track("b"), { repeat: "one" })).toBe("repeat");
    // Shuffle never picks the track that is playing.
    expect(nextIndex(queue, track("a"), { shuffle: true, rng: () => 0 })).toBe(1);
    expect(nextIndex(queue, track("a"), { shuffle: true, rng: () => 0.999 })).toBe(2);
    expect(nextIndex([], null)).toBeNull();
  });

  it("shuffles deterministically and keeps the current track first", () => {
    const order = shuffled(queue, track("b"), () => 0);
    expect(order[0].id).toBe("b");
    expect(new Set(order.map(keyOf)).size).toBe(3);
  });

  it("sums the runtime of the queue", () => {
    expect(totalDuration(queue)).toBe(300);
    expect(totalDuration([{ title: "x" }])).toBe(0);
  });
});
