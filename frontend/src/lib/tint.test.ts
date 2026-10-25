import { describe, expect, it } from "vitest";
import { tintFor } from "./tint";

describe("artwork tinting", () => {
  it("derives three in-range hues from a track", () => {
    const tint = tintFor("dQw4w9WgXcQ");
    expect(tint.hue).toBeGreaterThanOrEqual(0);
    expect(tint.hue).toBeLessThan(360);
    expect(tint.hue2).not.toBe(tint.hue);
    expect(tint.hue3).not.toBe(tint.hue);
  });

  it("is stable for the same song and different for another", () => {
    expect(tintFor("abc")).toEqual(tintFor("abc"));
    expect(tintFor("abc").hue).not.toBe(tintFor("xyz").hue);
  });

  it("still answers when there is nothing to read", () => {
    // A malformed row must not throw while the UI is painting.
    expect(() => tintFor(null)).not.toThrow();
    expect(() => tintFor(undefined)).not.toThrow();
    expect(tintFor("").hue).toBeGreaterThanOrEqual(0);
  });
});
