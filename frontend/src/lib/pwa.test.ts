import { renderHook, act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { canRegister, useConnection, useUpdateReady } from "./pwa";

describe("pwa helpers", () => {
  it("never registers a worker outside a production build", () => {
    // jsdom + vitest means import.meta.env.PROD is false
    expect(canRegister()).toBe(false);
  });

  it("tracks the network going away and coming back", () => {
    const { result } = renderHook(() => useConnection());
    expect(result.current.online).toBe(true);

    act(() => {
      Object.defineProperty(navigator, "onLine", { value: false, configurable: true });
      window.dispatchEvent(new Event("offline"));
    });
    expect(result.current.online).toBe(false);
    expect(result.current.since).toBeTypeOf("number");

    act(() => {
      Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
      window.dispatchEvent(new Event("online"));
    });
    expect(result.current.online).toBe(true);
    expect(result.current.since).toBeUndefined();
  });

  it("only offers a reload when a worker announced an update", () => {
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, reload },
      configurable: true,
    });
    const { result } = renderHook(() => useUpdateReady());
    expect(result.current.ready).toBe(false);

    act(() => {
      window.dispatchEvent(new Event("vyron:update-ready"));
    });
    expect(result.current.ready).toBe(true);
  });
});
