import { describe, expect, it } from "vitest";
import { artworkHiRes } from "./format";
describe("artwork", () => {
  it("upgrades a small YouTube thumbnail to the big file", () => {
    expect(artworkHiRes("https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg")).toBe(
      "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"
    );
    expect(artworkHiRes("https://i9.ytimg.com/vi_webp/abc123/mqdefault.webp")).toBe(
      "https://i.ytimg.com/vi/abc123/maxresdefault.jpg"
    );
  });

  it("leaves anything else, and an absent cover, alone", () => {
    const other = "https://cdn.example/cover.jpg";
    expect(artworkHiRes(other)).toBe(other);
    expect(artworkHiRes("https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg")).toBe(
      "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"
    );
    expect(artworkHiRes(null)).toBeNull();
    expect(artworkHiRes("")).toBeNull();
  });
});
