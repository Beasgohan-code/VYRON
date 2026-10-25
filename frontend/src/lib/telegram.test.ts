import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyViewport,
  bootClient,
  copyText,
  guardClose,
  insideTelegram,
  lockSwipes,
  paintChrome,
  shareLink,
  startTarget,
  syncScheme,
  useBackButton,
  watchClient,
} from "./telegram";

type AnyApp = Record<string, unknown>;

function install<T extends AnyApp>(app: T): T {
  (window as unknown as { Telegram: unknown }).Telegram = { WebApp: app };
  return app;
}

type Mock = ReturnType<typeof vi.fn>;
type FakeApp = AnyApp & { BackButton: Record<string, Mock> };

function fakeApp(overrides: AnyApp = {}): FakeApp {
  return {
    initData: "auth_date=1&hash=abc",
    initDataUnsafe: { start_param: "" },
    colorScheme: "dark",
    themeParams: { bg_color: "#101010", secondary_bg_color: "#181818", text_color: "#ffffff" },
    viewportHeight: 800,
    viewportStableHeight: 800,
    ready: vi.fn(),
    expand: vi.fn(),
    setHeaderColor: vi.fn(),
    setBackgroundColor: vi.fn(),
    setBottomBarColor: vi.fn(),
    enableClosingConfirmation: vi.fn(),
    disableClosingConfirmation: vi.fn(),
    disableVerticalSwipes: vi.fn(),
    enableVerticalSwipes: vi.fn(),
    openTelegramLink: vi.fn(),
    onEvent: vi.fn(),
    offEvent: vi.fn(),
    BackButton: { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() },
    ...overrides,
  } as FakeApp;
}

beforeEach(() => {
  delete (window as unknown as { Telegram?: unknown }).Telegram;
  document.documentElement.removeAttribute("data-scheme");
  document.documentElement.removeAttribute("data-keyboard");
});

afterEach(() => {
  delete (window as unknown as { Telegram?: unknown }).Telegram;
});

describe("boot", () => {
  it("tells the client we are ready and takes the screen", () => {
    const app = install(fakeApp());
    bootClient();
    expect(app.ready).toHaveBeenCalled();
    expect(app.expand).toHaveBeenCalled();
  });

  it("is a no-op in a plain browser", () => {
    expect(() => bootClient()).not.toThrow();
    expect(insideTelegram()).toBe(false);
  });

  it("knows when it is inside a real session", () => {
    install(fakeApp());
    expect(insideTelegram()).toBe(true);
  });
});

describe("colours", () => {
  it("mirrors the client's scheme onto the document", () => {
    install(fakeApp());
    expect(syncScheme().scheme).toBe("dark");
    expect(document.documentElement.dataset.scheme).toBe("dark");

    install(fakeApp({ colorScheme: "light" }));
    expect(syncScheme().scheme).toBe("light");
    expect(document.documentElement.dataset.scheme).toBe("light");
  });

  it("republishes the client's theme variables", () => {
    install(fakeApp());
    syncScheme();
    const style = document.documentElement.style;
    expect(style.getPropertyValue("--tg-bg-color")).toBe("#101010");
    expect(style.getPropertyValue("--tg-secondary-bg-color")).toBe("#181818");
  });

  it("paints the header and bottom bar from the client's own colours", () => {
    const app = install(fakeApp());
    paintChrome();
    // a string alias is tried first so a later theme switch keeps working
    expect(app.setHeaderColor).toHaveBeenCalledWith("bg_color");
    expect(app.setBackgroundColor).toHaveBeenCalledWith("bg_color");
    expect(app.setBottomBarColor).toHaveBeenCalledWith("#181818");
  });

  it("falls back to a literal colour when the client refuses the alias", () => {
    const app = install(
      fakeApp({
        setHeaderColor: vi.fn(() => {
          throw new Error("unknown colour");
        }),
      })
    );
    paintChrome();
    expect(app.setHeaderColor).toHaveBeenCalledWith("#101010");
  });
});

describe("viewport", () => {
  it("publishes the height and reports a closed keyboard", () => {
    install(fakeApp());
    const size = applyViewport();
    expect(size.height).toBe(800);
    expect(document.documentElement.dataset.keyboard).toBe("closed");
    expect(document.documentElement.style.getPropertyValue("--tg-vh")).toBe("800px");
  });

  it("notices the keyboard and gets the dock out of the way", () => {
    install(fakeApp({ viewportHeight: 420, viewportStableHeight: 800 }));
    const size = applyViewport();
    expect(size.keyboard).toBe(380);
    expect(document.documentElement.dataset.keyboard).toBe("open");
  });

  it("does not mistake browser chrome for a keyboard", () => {
    install(fakeApp({ viewportHeight: 740, viewportStableHeight: 800 }));
    applyViewport();
    expect(document.documentElement.dataset.keyboard).toBe("closed");
  });
});

describe("closing and swipes", () => {
  it("asks before closing only while it is asked to", () => {
    const app = install(fakeApp());
    guardClose(true);
    expect(app.enableClosingConfirmation).toHaveBeenCalled();
    guardClose(false);
    expect(app.disableClosingConfirmation).toHaveBeenCalled();
  });

  it("hands the vertical gesture back when nothing is full screen", () => {
    const app = install(fakeApp());
    lockSwipes(true);
    expect(app.disableVerticalSwipes).toHaveBeenCalled();
    lockSwipes(false);
    expect(app.enableVerticalSwipes).toHaveBeenCalled();
  });
});

describe("back button", () => {
  it("shows the arrow and routes it while there is somewhere to go", () => {
    const app = install(fakeApp());
    const onBack = vi.fn();
    const { unmount } = renderHook(() => useBackButton(true, onBack));

    expect(app.BackButton.show).toHaveBeenCalled();
    const handler = app.BackButton.onClick.mock.calls[0][0];
    handler();
    expect(onBack).toHaveBeenCalled();

    unmount();
    expect(app.BackButton.hide).toHaveBeenCalled();
    expect(app.BackButton.offClick).toHaveBeenCalledWith(handler);
  });

  it("stays hidden at the top of the app", () => {
    const app = install(fakeApp());
    renderHook(() => useBackButton(false, () => undefined));
    expect(app.BackButton.hide).toHaveBeenCalled();
    expect(app.BackButton.show).not.toHaveBeenCalled();
  });

  it("always calls the newest handler, not the one it was mounted with", () => {
    const app = install(fakeApp());
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = renderHook(({ fn }) => useBackButton(true, fn), {
      initialProps: { fn: first },
    });
    rerender({ fn: second });

    const handler = app.BackButton.onClick.mock.calls[0][0];
    handler();
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalled();
  });
});

describe("deep links", () => {
  it("reads a playlist, a mix, a search and a plain view", () => {
    expect(startTarget("playlist_abc123")).toEqual({ kind: "playlist", id: "abc123" });
    expect(startTarget("mix_chill")).toEqual({ kind: "mix", key: "chill" });
    expect(startTarget("search_arijit singh")).toEqual({ kind: "search", query: "arijit singh" });
    expect(startTarget("library")).toEqual({ kind: "view", view: "library" });
  });

  it("reads the parameter the client was opened with", () => {
    install(fakeApp({ initDataUnsafe: { start_param: "search_kesariya" } }));
    expect(startTarget()).toEqual({ kind: "search", query: "kesariya" });
  });

  it("ignores anything it does not understand", () => {
    expect(startTarget("")).toBeNull();
    expect(startTarget("nonsense_thing")).toBeNull();
    expect(startTarget("playlist_")).toBeNull();
    expect(startTarget("view_unknown")).toBeNull();
  });

  it("clips a hostile parameter instead of passing it on", () => {
    const target = startTarget(`search_${"a".repeat(500)}`);
    expect(target?.kind).toBe("search");
    expect((target as { query: string }).query.length).toBeLessThanOrEqual(200);
  });
});

describe("sharing", () => {
  it("opens the client's own share sheet", () => {
    const app = install(fakeApp());
    shareLink("https://t.me/VyronMusicBot", "listen");
    expect(app.openTelegramLink).toHaveBeenCalledWith(expect.stringContaining("t.me/share/url"));
    expect((app.openTelegramLink as ReturnType<typeof vi.fn>).mock.calls[0][0]).toContain(
      encodeURIComponent("https://t.me/VyronMusicBot")
    );
  });
});

describe("copying a link", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    Reflect.deleteProperty(navigator, "clipboard");
  });

  it("uses the async clipboard when the webview has one", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await expect(copyText("https://t.me/VyronMusicBot")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith("https://t.me/VyronMusicBot");
  });

  it("falls back to a hidden textarea when the clipboard is refused", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
      configurable: true,
    });
    const exec = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, "execCommand", { value: exec, configurable: true });
    await expect(copyText("https://t.me/VyronMusicBot")).resolves.toBe(true);
    expect(exec).toHaveBeenCalledWith("copy");
    // The scratch element must not be left behind in the sheet.
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("reports failure instead of throwing when both routes are closed", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
      configurable: true,
    });
    Object.defineProperty(document, "execCommand", {
      value: vi.fn().mockImplementation(() => {
        throw new Error("nope");
      }),
      configurable: true,
    });
    await expect(copyText("x")).resolves.toBe(false);
  });
});

describe("client events", () => {
  it("subscribes to theme and viewport and unsubscribes cleanly", () => {
    const app = install(fakeApp());
    const stop = watchClient({ onChange: () => undefined });
    const events = (app.onEvent as ReturnType<typeof vi.fn>).mock.calls.map(([name]) => name);
    expect(events).toContain("themeChanged");
    expect(events).toContain("viewportChanged");

    stop();
    expect(app.offEvent).toHaveBeenCalledTimes(events.length);
  });

  it("re-syncs when the client says the theme changed", () => {
    let fire: (() => void) | undefined;
    const app = install(
      fakeApp({
        onEvent: (name: string, handler: () => void) => {
          if (name === "themeChanged") fire = handler;
        },
      })
    );
    const stop = watchClient();
    act(() => {
      install({ ...app, colorScheme: "light" });
      fire?.();
    });
    expect(document.documentElement.dataset.scheme).toBe("light");
    stop();
  });
});
