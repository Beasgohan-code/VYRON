import { afterEach, describe, expect, it, vi } from "vitest";
import { morphCover } from "./morph";

afterEach(() => {
  document.documentElement.removeAttribute("data-morph");
  vi.restoreAllMocks();
});

describe("the cover that flies", () => {
  it("still runs the change on a browser with no View Transitions", () => {
    // jsdom has no `startViewTransition`; the change must happen anyway.
    const change = vi.fn();
    morphCover("open", change);
    expect(change).toHaveBeenCalledTimes(1);
    expect(document.documentElement.hasAttribute("data-morph")).toBe(false);
  });

  it("names the travelling cover for the length of the transition", async () => {
    let finish: () => void = () => undefined;
    const done = new Promise<void>((resolve) => {
      finish = resolve;
    });
    const start = vi.fn((callback: () => void) => {
      callback();
      return { finished: done };
    });
    (document as unknown as { startViewTransition: unknown }).startViewTransition = start;

    const change = vi.fn();
    morphCover("open", change);

    expect(start).toHaveBeenCalledTimes(1);
    expect(change).toHaveBeenCalledTimes(1);
    expect(document.documentElement.getAttribute("data-morph")).toBe("open");

    finish();
    await Promise.resolve();
    await Promise.resolve();
    expect(document.documentElement.hasAttribute("data-morph")).toBe(false);
  });

  it("runs the change once when the platform throws", () => {
    const start = vi.fn(() => {
      throw new Error("not supported here");
    });
    (document as unknown as { startViewTransition: unknown }).startViewTransition = start;
    const change = vi.fn();
    morphCover("close", change);
    expect(change).toHaveBeenCalledTimes(1);
    expect(document.documentElement.hasAttribute("data-morph")).toBe(false);
  });
});
