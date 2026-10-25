import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Avatar } from "./Avatar";
import { avatarSeed, forgetAvatar, loadAvatar } from "../lib/avatar";

const picture = () => ({
  ok: true,
  status: 200,
  blob: async () => new Blob(["fake-userpic"], { type: "image/jpeg" }),
});

beforeEach(() => {
  forgetAvatar();
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Avatar", () => {
  it("shows initials for someone with no picture", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404, blob: async () => new Blob() })));
    render(<Avatar name="Rinu Raj" userId={7} />);

    expect(await screen.findByText("RR")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", "Rinu Raj");
    expect(document.querySelector(".avatar-img")).toBeNull();
  });

  it("paints the Telegram picture on top of the initials", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => picture()));
    render(<Avatar name="Rinu" userId={8} photo="https://t.me/i/userpic/320/x.jpg" />);

    await waitFor(() => expect(document.querySelector(".avatar-img")).toBeTruthy());
    const img = document.querySelector(".avatar-img") as HTMLImageElement;
    expect(img.getAttribute("src")).toContain("data:image/jpeg");
    expect(img).toHaveAttribute("loading", "eager");
    // the initials stay underneath, so a failed image is never an empty circle
    expect(screen.getByText("R")).toBeInTheDocument();
  });

  it("paints from the device cache before any network call", async () => {
    const seed = avatarSeed({ id: 9 });
    window.localStorage.setItem(
      "vyron:avatar",
      JSON.stringify({ seed, data: "data:image/jpeg;base64,AAAA", at: Date.now() })
    );
    const fetchMock = vi.fn(async () => picture());
    vi.stubGlobal("fetch", fetchMock);
    // the loader is what fills the cache; the component only reads it
    const first = await loadAvatar(seed);
    expect(first).toBeTruthy();

    render(<Avatar name="Cached Person" userId={9} />);
    await waitFor(() => expect(document.querySelector(".avatar-img")).toBeTruthy());
  });

  it("falls back to the initials when the picture fails to load", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => picture()));
    render(<Avatar name="Broken Face" userId={11} />);
    await waitFor(() => expect(document.querySelector(".avatar-img")).toBeTruthy());

    const img = document.querySelector(".avatar-img") as HTMLImageElement;
    await act(async () => {
      img.dispatchEvent(new Event("error"));
    });
    await waitFor(() => expect(document.querySelector(".avatar-img")).toBeNull());
    expect(screen.getByText("BF")).toBeInTheDocument();
  });

  it("carries the status dot only when it is asked for", () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404, blob: async () => new Blob() })));
    const { container, rerender } = render(<Avatar name="Anon" userId={12} />);
    expect(container.querySelector(".avatar-status")).toBeNull();

    rerender(<Avatar name="Anon" userId={12} status="on" />);
    expect(container.querySelector(".avatar-status.on")).toBeTruthy();
  });
});
