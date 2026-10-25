import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Aurora } from "./Aurora";
import { Count } from "./Count";
import { Reactor } from "./Reactor";

/**
 * jsdom has no WebGL — these components must fall back to CSS instead of
 * throwing or shipping a canvas nobody can render.
 */
describe("three.js visuals", () => {
  it("renders the aurora CSS fallback without WebGL", () => {
    const { container } = render(<Aurora className="hero-aurora" />);
    const node = container.querySelector(".aurora");
    expect(node).not.toBeNull();
    expect(node?.getAttribute("data-webgl")).toBe("off");
    expect(container.querySelector("canvas")).toBeNull();
  });

  it("renders the reactor CSS orb without WebGL", async () => {
    const { container } = render(<Reactor playing />);
    const node = container.querySelector(".reactor");
    expect(node).not.toBeNull();
    expect(node?.getAttribute("data-playing")).toBe("on");
    expect(await screen.findByText((_, element) => element?.className === "reactor-fallback")).toBeTruthy();
  });

  it("does not touch the analyser until the scene can render", () => {
    let calls = 0;
    render(
      <Reactor
        analyser={() => {
          calls += 1;
          return null;
        }}
      />
    );
    expect(calls).toBe(0);
  });
});

describe("anime.js counters", () => {
  it("prints the value immediately", () => {
    render(<Count value={42} />);
    expect(screen.getByText("42")).toBeInTheDocument();
  });
});
