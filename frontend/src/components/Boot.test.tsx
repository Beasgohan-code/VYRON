import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "../App";
import { AppProvider } from "../lib/store";
import { stubApi } from "../test-setup";

function mount() {
  return render(
    <AppProvider>
      <App />
    </AppProvider>
  );
}

describe("boot and access", () => {
  it("shows the boot screen with real stages, then gets out of the way", async () => {
    mount();
    const boot = document.querySelector(".boot-screen") as HTMLElement;
    expect(boot).not.toBeNull();
    expect(boot.textContent).toMatch(/Interface/);
    expect(boot.textContent).toMatch(/Telegram session/);

    // once the API answers, the stages complete and the overlay leaves
    await waitFor(
      () => {
        expect(document.querySelector(".boot-screen")).toBeNull();
      },
      { timeout: 4000 }
    );
  });

  it("explains how to get in when there is no Telegram session", async () => {
    vi.stubGlobal("fetch", () =>
      Promise.resolve({ ok: false, status: 401, json: async () => ({ ok: false }) } as Response)
    );
    mount();

    expect(await screen.findByText(/inside Telegram/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open @VyronMusicBot/i })).toHaveAttribute(
      "href",
      "https://t.me/VyronMusicBot"
    );
  });

  it("keeps working when the server is unreachable", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new Error("network down")));
    mount();
    expect(await screen.findByText(/Cannot reach the VYRON server/i)).toBeInTheDocument();
  });

  it("marks the session stage offline instead of pretending", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new Error("network down")));
    mount();
    await waitFor(() => expect(document.querySelector(".boot-screen")?.textContent).toMatch(/offline/));
  });

  it("still renders the unlocked app normally", async () => {
    stubApi();
    mount();
    expect(await screen.findByText("Neon Skyline")).toBeInTheDocument();
    expect(document.querySelector(".gate")).toBeNull();
  });
});

// keep the unused import tree-shaken away in strict TS
