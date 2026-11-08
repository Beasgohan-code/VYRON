import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RoomLyrics } from "./RoomLyrics";

const lyrics = vi.fn();

vi.mock("../lib/api", () => ({
  api: { lyrics: (...args: unknown[]) => lyrics(...args) },
}));

const synced = [
  { time: 0, text: "" },
  { time: 4.2, text: "Dil ka jo haal hai" },
  { time: 9.6, text: "Woh tera hi hai" },
  { time: 15.1, text: " " },
  { time: 19.4, text: "Na jaane kyun" },
];

function draw(position: number, extra: Partial<Parameters<typeof RoomLyrics>[0]> = {}) {
  return render(
    <RoomLyrics
      title="Kesariya"
      artist="Arijit Singh"
      duration={268}
      position={position}
      playing
      {...extra}
    />
  );
}

beforeEach(() => {
  lyrics.mockReset();
  lyrics.mockResolvedValue({ ok: true, synced: true, lines: synced });
});

describe("RoomLyrics", () => {
  it("highlights the line for the room's second, not the phone's", async () => {
    const { container, rerender } = draw(5);

    const active = await screen.findByText("Dil ka jo haal hai");
    expect(active).toHaveAttribute("data-active", "true");

    /* The room moves on — the same component follows, because the position it
       is given comes from the socket's clock. */
    rerender(
      <RoomLyrics title="Kesariya" artist="Arijit Singh" duration={268} position={11} playing />
    );
    expect(screen.getByText("Woh tera hi hai")).toHaveAttribute("data-active", "true");
    expect(screen.getByText("Dil ka jo haal hai")).not.toHaveAttribute("data-active");
    expect(container.querySelectorAll('[data-active="true"]')).toHaveLength(1);
  });

  it("marks the neighbours so the eye can find its place", async () => {
    draw(11);
    await screen.findByText("Woh tera hi hai");
    expect(screen.getByText("Dil ka jo haal hai")).toHaveAttribute("data-near", "true");
    expect(screen.getByText("Woh tera hi hai")).not.toHaveAttribute("data-near");
  });

  it("draws an instrumental gap as a bar instead of an empty row", async () => {
    const { container } = draw(15.5);
    await screen.findByText("Na jaane kyun");
    const blanks = container.querySelectorAll("li.blank");
    expect(blanks.length).toBe(2); // the two untimed/whitespace lines
    expect(blanks[0].textContent).toBe("");
    expect(blanks[0].querySelector("i")).not.toBeNull();
  });

  it("jumps the room when a line is tapped, and only when allowed", async () => {
    const seek = vi.fn();
    const { unmount } = draw(5, { onSeek: seek });
    fireEvent.click(await screen.findByText("Na jaane kyun"));
    expect(seek).toHaveBeenCalledWith(19.4);
    unmount();

    /* A listener who cannot drive the room gets plain text, not a dead button. */
    draw(5);
    const line = await screen.findByText("Na jaane kyun");
    expect(line).not.toHaveAttribute("role", "button");
  });

  it("does not ask for lyrics twice for the same track", async () => {
    const { rerender } = draw(5);
    await screen.findByText("Dil ka jo haal hai");
    rerender(
      <RoomLyrics title="Kesariya" artist="Arijit Singh" duration={268} position={40} playing />
    );
    expect(lyrics).toHaveBeenCalledTimes(1);
    expect(lyrics).toHaveBeenCalledWith("Kesariya", "Arijit Singh", 268);
  });

  it("asks again when the room moves to another track", async () => {
    const { rerender } = draw(5);
    await screen.findByText("Dil ka jo haal hai");
    lyrics.mockResolvedValue({ ok: true, lines: [{ time: 0, text: "Tum hi ho" }] });
    rerender(
      <RoomLyrics title="Tum Hi Ho" artist="Arijit Singh" duration={260} position={1} playing />
    );
    expect(await screen.findByText("Tum hi ho")).toBeInTheDocument();
    expect(lyrics).toHaveBeenCalledTimes(2);
  });

  it("says so when there are none, without breaking the room", async () => {
    lyrics.mockResolvedValue({ ok: true, lines: [], text: "" });
    draw(5);
    expect(await screen.findByText("No lyrics for this one.")).toBeInTheDocument();
  });

  it("renders plain lyrics inline when the source has no timings", async () => {
    lyrics.mockResolvedValue({ ok: true, text: "first verse\n\nsecond verse" });
    const { container } = draw(5);
    expect(await screen.findByText("first verse")).toBeInTheDocument();
    expect(container.querySelectorAll(".lr-lyrics.plain p")).toHaveLength(2);
  });

  it("survives a failed lookup", async () => {
    lyrics.mockRejectedValue(new Error("offline"));
    draw(5);
    expect(await screen.findByText("No lyrics for this one.")).toBeInTheDocument();
  });
});
