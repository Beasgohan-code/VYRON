import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "./App";
import { AppProvider } from "./lib/store";
import { stubApi } from "./test-setup";

async function nav(label: string): Promise<HTMLElement> {
  return waitFor(() => {
    const rail = document.querySelector(".rail") as HTMLElement;
    const button = within(rail)
      .getAllByRole("button")
      .find((item) => item.textContent?.trim() === label);
    if (!button) throw new Error(`nav item ${label} missing`);
    return button;
  });
}

function mount() {
  return render(
    <AppProvider>
      <App />
    </AppProvider>
  );
}

describe("VYRON Mini App", () => {
  it("renders the shell, greeting and trending shelf", async () => {
    mount();
    expect(screen.getAllByText("VYRON").length).toBeGreaterThan(0);
    expect(await screen.findByText(/Music hits different here/i)).toBeInTheDocument();
    expect(await screen.findByText("Neon Skyline")).toBeInTheDocument();
  });

  it("navigates between views", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(await nav("Library"));
    expect(await screen.findByText("Liked songs")).toBeInTheDocument();
    expect(await screen.findByText("Saved track")).toBeInTheDocument();

    await user.click(await nav("Rooms"));
    expect(await screen.findByText("No active rooms")).toBeInTheDocument();

    await user.click(await nav("You"));
    expect(await screen.findByText("Test Listener")).toBeInTheDocument();
    expect(screen.getByText("Appearance")).toBeInTheDocument();
  });

  it("persists the accent choice", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(await nav("You"));
    const dots = document.querySelectorAll(".accent-dot");
    expect(dots.length).toBe(6);

    await user.click(dots[2] as HTMLElement);
    expect(document.documentElement.dataset.accent).toBe("cyan");
    expect(localStorage.getItem("vyron:accent")).toBe("cyan");
  });

  it("runs a search and shows results", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(await nav("Search"));
    const input = await screen.findByPlaceholderText(/Search songs, artists or paste a link/i);
    await user.type(input, "neon");
    await user.click(document.querySelector(".field-go") as HTMLElement);

    await waitFor(() => expect(screen.getByText("Slow Motion")).toBeInTheDocument());
    expect(localStorage.getItem("vyron:recent")).toContain("neon");
  });

  it("plays a result in the app, shows the dock and opens the player", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(await nav("Search"));
    const input = await screen.findByPlaceholderText(/Search songs, artists or paste a link/i);
    await user.type(input, "neon");
    await user.click(document.querySelector(".field-go") as HTMLElement);

    const row = await waitFor(() => {
      const node = document.querySelector(".track-row") as HTMLElement;
      expect(node).not.toBeNull();
      return node;
    });
    await user.click(row);

    const dock = await waitFor(() => {
      const node = document.querySelector(".dock") as HTMLElement;
      expect(node).not.toBeNull();
      return node;
    });
    expect(within(dock).getByText("Neon Skyline")).toBeInTheDocument();

    await user.click(within(dock).getByLabelText("Open full player"));
    const dialog = await screen.findByRole("dialog", { name: "Player" });
    expect(within(dialog).getByLabelText("Toggle lyrics")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Seek")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Player" })).toBeNull());
  });

  it("shows the owner journal and system health", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(await nav("Owner"));
    expect(await screen.findByText("VYRON preview online")).toBeInTheDocument();
    expect(await screen.findByText("MongoDB unavailable")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /System/i }));
    expect(await screen.findByText("storage")).toBeInTheDocument();
    expect(screen.getByText("mongo")).toBeInTheDocument();
  });

  it("filters the journal down to errors", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(await nav("Owner"));
    await screen.findByText("VYRON preview online");
    await user.click(screen.getByRole("button", { name: /^Errors/i }));
    await waitFor(() => {
      const active = document.querySelector(".chip.active");
      expect(active?.textContent).toMatch(/Errors/);
    });
  });

  it("opens the download sheet from the hero", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole("button", { name: /Download/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Link or search/i)).toBeInTheDocument();
  });

  it("opens the keyboard cheat sheet with ?", async () => {
    const user = userEvent.setup();
    mount();

    await user.keyboard("?");
    const dialog = await screen.findByRole("dialog", { name: /keyboard shortcuts/i });
    expect(within(dialog).getByText(/Play \/ pause/i)).toBeInTheDocument();
    expect(within(dialog).getByText("Space")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: /keyboard shortcuts/i })).toBeNull()
    );
  });

  it("offers to continue a session this device left behind", async () => {
    const saved = {
      version: 2,
      queue: [
        { id: "s1", title: "Left Behind", duration: 240, uploader: "Someone" },
        { id: "s2", title: "Next Up", duration: 180, uploader: "Someone" },
      ],
      index: 0,
      position: 96,
      rate: 1,
      volume: 0.8,
      muted: false,
      repeat: "all",
      shuffle: false,
      savedAt: Date.now(),
    };
    localStorage.setItem("vyron:session", JSON.stringify(saved));
    mount();

    expect(await screen.findByText("Left Behind")).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 · 1:36 in/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /Resume/i })).toBeInTheDocument());
    localStorage.removeItem("vyron:session");
  });

  it("badges the engine as off when the assistant is missing", async () => {
    stubApi({ streaming: false });
    mount();

    await waitFor(() => expect(document.querySelector(".status-dot")).not.toBeNull());
    expect(document.querySelector(".status-dot.on")).toBeNull();
  });
});
