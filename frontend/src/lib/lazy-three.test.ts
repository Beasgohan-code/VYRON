import { afterEach, describe, expect, it, vi } from "vitest";
import { loadThree, resetThreeLoader, visualsWorthLoading, whenIdle } from "./lazy-three";

function network(info: { saveData?: boolean; effectiveType?: string }) {
  Object.defineProperty(navigator, "connection", { value: info, configurable: true });
}

afterEach(() => {
  Object.defineProperty(navigator, "connection", { value: undefined, configurable: true });
  resetThreeLoader();
});

describe("lazy three.js", () => {
  it("skips the backdrop on a metered or 2G connection", () => {
    network({ saveData: true });
    expect(visualsWorthLoading()).toBe(false);
    network({ effectiveType: "2g" });
    expect(visualsWorthLoading()).toBe(false);
    network({ effectiveType: "4g" });
    expect(visualsWorthLoading()).toBe(true);
    Object.defineProperty(navigator, "connection", { value: undefined, configurable: true });
    expect(visualsWorthLoading()).toBe(true); // no Network Information API: assume fine
  });

  it("downloads the module once, no matter how many visuals ask", async () => {
    const first = loadThree();
    const second = loadThree();
    expect(second).toBe(first);
  });

  it("defers the work until the shell has painted", async () => {
    vi.useFakeTimers();
    const work = vi.fn();
    const cancel = whenIdle(work);
    expect(work).not.toHaveBeenCalled();
    vi.advanceTimersByTime(200);
    expect(work).toHaveBeenCalledTimes(1);

    const second = vi.fn();
    cancel();
    whenIdle(second);
    vi.advanceTimersByTime(200);
    expect(second).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
