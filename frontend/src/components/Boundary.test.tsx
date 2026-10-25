import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Boundary } from "../components/Boundary";

const reportCrash = vi.fn();
vi.mock("../lib/api", () => ({
  reportCrash: (detail: unknown) => reportCrash(detail),
}));

function Boom({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("kaboom in a view");
  return <p>all good</p>;
}

describe("Boundary", () => {
  beforeEach(() => {
    reportCrash.mockReset();
    // React prints the caught error to the console; that noise is expected here
    // and would otherwise hide a real failure in the output.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders children when nothing is wrong", () => {
    render(
      <Boundary>
        <Boom shouldThrow={false} />
      </Boundary>
    );
    expect(screen.getByText("all good")).toBeTruthy();
    expect(reportCrash).not.toHaveBeenCalled();
  });

  it("shows a readable card instead of a blank screen", () => {
    render(
      <Boundary>
        <Boom shouldThrow />
      </Boundary>
    );
    expect(screen.getByText("Something broke on this screen")).toBeTruthy();
    expect(screen.getByText("kaboom in a view")).toBeTruthy();
    // The promise to the listener: their audio is not what broke.
    expect(screen.getByText(/voice chat is playing/i)).toBeTruthy();
  });

  it("writes the crash to the owner journal", () => {
    render(
      <Boundary>
        <Boom shouldThrow />
      </Boundary>
    );
    expect(reportCrash).toHaveBeenCalledTimes(1);
    const detail = reportCrash.mock.calls[0][0] as { message: string; scope: string; stack: string };
    expect(detail.message).toBe("kaboom in a view");
    expect(detail.scope).toBe("render");
    expect(typeof detail.stack).toBe("string");
  });

  it("lets the user try again without reloading", async () => {
    const user = userEvent.setup();
    render(
      <Boundary>
        <Boom shouldThrow />
      </Boundary>
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));
    // Still broken, so the card stays rather than flashing the broken view.
    expect(screen.getByText("Something broke on this screen")).toBeTruthy();
    expect(reportCrash).toHaveBeenCalledTimes(2);
  });

  it("offers a reload as the way out", () => {
    render(
      <Boundary>
        <Boom shouldThrow />
      </Boundary>
    );
    expect(screen.getByRole("button", { name: "Reload the app" })).toBeTruthy();
  });
});
