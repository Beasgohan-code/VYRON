import { describe, expect, it } from "vitest";
import { activeLyricLine } from "./format";

const lines = [
  { time: 0, text: "" },
  { time: 12.5, text: "first" },
  { time: 18, text: "second" },
  { time: 26, text: "third" },
];

describe("synced lyrics", () => {
  it("has no active line before the first one starts", () => {
    expect(activeLyricLine([{ time: 5, text: "x" }], 0)).toBe(-1);
    expect(activeLyricLine([], 10)).toBe(-1);
    expect(activeLyricLine(undefined, 10)).toBe(-1);
  });

  it("follows playback through the timings", () => {
    expect(activeLyricLine(lines, 0)).toBe(0);
    expect(activeLyricLine(lines, 13)).toBe(1);
    expect(activeLyricLine(lines, 18.1)).toBe(2);
    expect(activeLyricLine(lines, 999)).toBe(3);
  });

  it("lights a line slightly early, never late", () => {
    expect(activeLyricLine(lines, 12.2)).toBe(1);   // 0.4 s lead
    expect(activeLyricLine(lines, 11.5)).toBe(0);   // still the previous line
  });
});
