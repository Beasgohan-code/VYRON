import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AVATAR_KEY,
  avatarSeed,
  cachedAvatar,
  forgetAvatar,
  loadAvatar,
  primeAvatar,
} from "./avatar";

const picture = (type = "image/jpeg") => ({
  ok: true,
  status: 200,
  blob: async () => new Blob(["fake-userpic"], { type }),
});

const SEED = avatarSeed({ id: 7, photo: "https://t.me/i/userpic/320/aaa.jpg" });

beforeEach(() => {
  forgetAvatar();
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  delete (window as unknown as { Telegram?: unknown }).Telegram;
});

describe("which picture is which", () => {
  it("is empty without a user, so nothing is requested", () => {
    expect(avatarSeed(undefined)).toBe("");
    expect(avatarSeed({})).toBe("");
  });

  it("changes when the Telegram picture changes", () => {
    const one = avatarSeed({ id: 7, photo: "https://t.me/i/userpic/320/aaa.jpg" });
    const two = avatarSeed({ id: 7, photo: "https://t.me/i/userpic/320/bbb.jpg" });
    expect(one).not.toBe(two);
    expect(one).toContain("7");
  });
});

describe("loading the face", () => {
  it("asks the server with the Telegram session and keeps the result", async () => {
    (window as unknown as { Telegram: unknown }).Telegram = {
      WebApp: { initData: "user=%7B%7D&hash=abc" },
    };
    const fetchMock = vi.fn(async () => picture());
    vi.stubGlobal("fetch", fetchMock);

    const data = await loadAvatar(SEED);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/avatar");
    expect((init.headers as Record<string, string>)["X-Init-Data"]).toBe("user=%7B%7D&hash=abc");

    expect(data?.startsWith("data:image/jpeg")).toBe(true);
    expect(cachedAvatar(SEED)).toBe(data);
    expect(JSON.parse(window.localStorage.getItem(AVATAR_KEY) ?? "{}").seed).toBe(SEED);
  });

  it("does not refetch the same face in the same session", async () => {
    const fetchMock = vi.fn(async () => picture());
    vi.stubGlobal("fetch", fetchMock);

    await loadAvatar(SEED);
    await loadAvatar(SEED);
    await primeAvatar({ id: 7, photo: "https://t.me/i/userpic/320/aaa.jpg" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shares one request between callers that ask at the same time", async () => {
    const fetchMock = vi.fn(async () => picture());
    vi.stubGlobal("fetch", fetchMock);

    const [a, b] = await Promise.all([loadAvatar(SEED), loadAvatar(SEED)]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(a).toBe(b);
  });

  it("treats 'no picture' as an answer, not an error", async () => {
    const fetchMock = vi.fn(async () => ({ ok: false, status: 404, blob: async () => new Blob() }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadAvatar(SEED)).resolves.toBeNull();
    expect(cachedAvatar(SEED)).toBeNull();
  });

  it("survives being offline", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      })
    );

    await expect(loadAvatar(SEED)).resolves.toBeNull();
  });

  it("keeps the last picture when a refresh fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => picture()));
    const first = await loadAvatar(SEED);
    expect(first).toBeTruthy();

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      })
    );
    forgetAvatar();
    window.localStorage.setItem(
      AVATAR_KEY,
      JSON.stringify({ seed: SEED, data: first, at: Date.now() })
    );

    expect(cachedAvatar(SEED)).toBe(first);
    await expect(loadAvatar(SEED)).resolves.toBe(first);
  });

  it("refuses a body that is not an image", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => picture("text/html")));
    await expect(loadAvatar(SEED)).resolves.toBeNull();
  });

  it("does not blow up when storage is full", async () => {
    const spy = vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    vi.stubGlobal("fetch", vi.fn(async () => picture()));

    const data = await loadAvatar(SEED);
    expect(data).toBeTruthy();
    spy.mockRestore();
  });
});
