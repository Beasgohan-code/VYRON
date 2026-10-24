import { describe, expect, it } from "vitest";
import { SHORTCUTS, isTyping, shortcutFor } from "./keys";

const key = (value: string, extra: Partial<KeyboardEvent> = {}) => ({ key: value, ...extra });

describe("keyboard shortcuts", () => {
  it("maps the transport keys", () => {
    expect(shortcutFor(key(" "))).toBe("toggle");
    expect(shortcutFor(key("ArrowRight"))).toBe("seekForward");
    expect(shortcutFor(key("ArrowRight", { shiftKey: true }))).toBe("next");
    expect(shortcutFor(key("ArrowLeft", { shiftKey: true }))).toBe("prev");
    expect(shortcutFor(key("ArrowUp"))).toBe("volumeUp");
    expect(shortcutFor(key("ArrowDown"))).toBe("volumeDown");
    expect(shortcutFor(key("m"))).toBe("mute");
    expect(shortcutFor(key("/"))).toBe("search");
    expect(shortcutFor(key("?"))).toBe("help");
    expect(shortcutFor(key("l"))).toBe("like");
  });

  it("leaves typing alone — except Escape", () => {
    const input = { tagName: "INPUT" } as unknown as HTMLElement;
    expect(isTyping(input)).toBe(true);
    expect(shortcutFor(key(" "), input)).toBeNull();
    expect(shortcutFor(key("n"), input)).toBeNull();
    expect(shortcutFor(key("Escape"), input)).toBe("escape");
  });

  it("does not swallow browser chords", () => {
    expect(shortcutFor(key("k", { metaKey: true }))).toBeNull();
    expect(shortcutFor(key("l", { ctrlKey: true }))).toBeNull();
    expect(shortcutFor(key("?"))).toBe("help");
    expect(shortcutFor(key("x"))).toBeNull();
  });

  it("ships an overlay entry for every action it can produce", () => {
    const listed = new Set(SHORTCUTS.map((item) => item.id));
    for (const id of ["toggle", "next", "prev", "seekForward", "seekBack", "mute", "search", "help", "escape"]) {
      expect(listed.has(id as never)).toBe(true);
    }
    expect(SHORTCUTS.every((item) => item.keys.length > 0)).toBe(true);
  });
});
