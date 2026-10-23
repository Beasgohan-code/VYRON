import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "./App";
import { AppProvider } from "./lib/store";
import { stubApi } from "./test-setup";

function nav(label: string): HTMLElement {
  const sidebar = document.querySelector(".nav") as HTMLElement;
  const button = within(sidebar)
    .getAllByRole("button")
    .find((item) => item.textContent?.trim() === label);
  if (!button) throw new Error(`nav item ${label} missing`);
  return button;
}

function mount() {
  return render(
    <AppProvider>
      <App />
    </AppProvider>
  );
}

describe("VYRON Player", () => {
  it("renders the shell, hero and now-playing rail", async () => {
    mount();
    expect(screen.getByText("VYRON")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Music hits different here/i)).toBeInTheDocument());

    const rail = screen.getByText("Now playing").closest("article") as HTMLElement;
    expect(within(rail).getByText("Midnight Drive")).toBeInTheDocument();
    expect(within(rail).getByText("Lumen")).toBeInTheDocument();

    // trending shelf is populated from /api/home
    expect(await screen.findByText("Neon Skyline")).toBeInTheDocument();
  });

  it("navigates between views", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(nav("Library"));
    expect(await screen.findByText("Liked songs", { selector: "strong" })).toBeInTheDocument();

    await user.click(nav("Queue"));
    expect(await screen.findByText("Autoplay")).toBeInTheDocument();
    expect(screen.getAllByText("Neon Skyline").length).toBeGreaterThan(0);

    await user.click(nav("Settings"));
    expect(await screen.findByText("Profile & settings")).toBeInTheDocument();
    expect(await screen.findByText("owner")).toBeInTheDocument();
    expect(screen.getByText("Owner tools")).toBeInTheDocument();
    expect(screen.getByText("Beat")).toBeInTheDocument();
  });

  it("switches accent and persists it", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(nav("Settings"));
    const dots = document.querySelectorAll(".accent-dot");
    expect(dots.length).toBe(6);

    await user.click(dots[2] as HTMLElement);
    expect(document.documentElement.dataset.accent).toBe("cyan");
    expect(localStorage.getItem("vyron:accent")).toBe("cyan");
  });

  it("runs a search and shows results", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(nav("Search"));
    const input = await screen.findByPlaceholderText(/Search or paste a YouTube link/i);
    await user.type(input, "neon");
    await user.click(document.querySelector(".search-go") as HTMLElement);


    await waitFor(() => expect(screen.getByText("Slow Motion")).toBeInTheDocument());
    expect(localStorage.getItem("vyron:recent")).toContain("neon");
  });

  it("badges file mode when there is no assistant session", async () => {
    stubApi({ streaming: false });
    mount();

    await waitFor(() => expect(screen.getByText("Now playing")).toBeInTheDocument());
    const badge = document.querySelector(".np-flags .tag.ghost");
    expect(badge).not.toBeNull();
    expect(badge?.textContent).toContain("file mode");
  });

  it("focuses the topbar search with the / shortcut", async () => {
    const user = userEvent.setup();
    mount();

    await user.keyboard("/");
    const input = screen.getByPlaceholderText(/Search songs, artists or paste a link/i);
    expect(document.activeElement).toBe(input);
  });

  it("plays a result in the app and opens the full player", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(nav("Search"));
    const input = await screen.findByPlaceholderText(/Search or paste a YouTube link/i);
    await user.type(input, "neon");
    await user.click(document.querySelector(".search-go") as HTMLElement);

    const row = await waitFor(() => {
      const node = document.querySelector(".result") as HTMLElement;
      expect(node).not.toBeNull();
      return node;
    });
    await user.click(within(row).getByLabelText("Play now"));

    const dock = await waitFor(() => {
      const node = document.querySelector(".playbar") as HTMLElement;
      expect(node).not.toBeNull();
      return node;
    });
    expect(within(dock).getByText("Neon Skyline")).toBeInTheDocument();
    expect(within(dock).getByLabelText("Seek")).toBeInTheDocument();

    await user.click(within(dock).getByLabelText("Open full player"));
    const dialog = await screen.findByRole("dialog", { name: "Player" });
    expect(within(dialog).getByLabelText("Toggle lyrics")).toBeInTheDocument();
    expect(within(dialog).getByText(/in queue/i)).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Player" })).toBeNull());
  });

  it("opens the command palette with ⌘K and jumps to the API console", async () => {
    const user = userEvent.setup();
    mount();

    await user.keyboard("{Meta>}k{/Meta}");
    const palette = await screen.findByRole("dialog", { name: "Command palette" });
    expect(within(palette).getByPlaceholderText(/Jump to a view/i)).toBeInTheDocument();

    await user.type(within(palette).getByPlaceholderText(/Jump to a view/i), "api");
    await user.click(within(palette).getByText("Music API"));

    expect(
      await screen.findByText(
        "A professional, Eldian-compatible music API served by this exact deployment — no second service, no second port."
      )
    ).toBeInTheDocument();
    expect(await screen.findByText("vyrn_fix…0000")).toBeInTheDocument();
    expect(document.querySelector(".api-status.on")).not.toBeNull();
  });

  it("shows API endpoints and a copyable base URL", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(nav("Music API"));
    expect(await screen.findByText("/v1/tracks")).toBeInTheDocument();
    expect(screen.getByText("http://localhost:8099")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create key/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rotate api-bot/i })).toBeInTheDocument();
    expect(screen.getByText("Live traffic")).toBeInTheDocument();
  });

  it("opens the keyboard cheat sheet with ? and closes with escape", async () => {
    const user = userEvent.setup();
    mount();

    await user.keyboard("?");
    const sheet = await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    expect(within(sheet).getByText("Command palette")).toBeInTheDocument();
    expect(within(sheet).getByText("Play or pause")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).toBeNull());
  });

  it("opens the download modal from the rail", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByText("Download music"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Format")).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Link or search/i)).toBeInTheDocument();
  });
});
