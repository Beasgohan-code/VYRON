import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ErrorBoundary } from "../components/ErrorBoundary";

const reportCrash = vi.fn();
vi.mock("../lib/api", () => ({
  reportCrash: (detail: unknown) => reportCrash(detail),
}));

function Boom({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("kaboom in a view");
  return <p>all good</p>;
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    reportCrash.mockReset();
    // React prints the caught error to the console; that noise is expected here
    // and would otherwise bury a real failure in the output.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders children when nothing is wrong", () => {
    render(
      <ErrorBoundary>
        <Boom shouldThrow={false} />
      </ErrorBoundary>
    );
    expect(screen.getByText("all good")).toBeTruthy();
    expect(reportCrash).not.toHaveBeenCalled();
  });

  it("keeps the shell alive with a pane instead of a blank screen", () => {
    render(
      <ErrorBoundary where="player">
        <Boom shouldThrow />
      </ErrorBoundary>
    );
    expect(screen.getByText("This screen stopped working")).toBeTruthy();
    expect(screen.getByText(/The player hit an error/)).toBeTruthy();
    expect(screen.getByText("kaboom in a view")).toBeTruthy();
  });

  it("fills the screen in root mode and promises the audio survived", () => {
    const { container } = render(
      <ErrorBoundary full>
        <Boom shouldThrow />
      </ErrorBoundary>
    );
    expect(screen.getByText("Something broke on this screen")).toBeTruthy();
    expect(screen.getByText(/voice chat is playing are unaffected/)).toBeTruthy();
    expect(container.querySelector(".crash-full")).toBeTruthy();
  });

  it("writes the crash to the owner journal with its scope", () => {
    render(
      <ErrorBoundary where="library">
        <Boom shouldThrow />
      </ErrorBoundary>
    );
    expect(reportCrash).toHaveBeenCalledTimes(1);
    const detail = reportCrash.mock.calls[0][0] as { message: string; scope: string; stack: string };
    expect(detail.message).toBe("kaboom in a view");
    expect(detail.scope).toBe("view:library");
    expect(typeof detail.stack).toBe("string");
  });

  it("labels a root crash as a render failure", () => {
    render(
      <ErrorBoundary full>
        <Boom shouldThrow />
      </ErrorBoundary>
    );
    expect((reportCrash.mock.calls[0][0] as { scope: string }).scope).toBe("render");
  });

  it("lets the user try again without reloading", async () => {
    const user = userEvent.setup();
    render(
      <ErrorBoundary>
        <Boom shouldThrow />
      </ErrorBoundary>
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));
    // Still broken, so the pane stays rather than flashing the broken view.
    expect(screen.getByText("This screen stopped working")).toBeTruthy();
    expect(reportCrash).toHaveBeenCalledTimes(2);
  });

  it("offers a reload as the way out", () => {
    render(
      <ErrorBoundary>
        <Boom shouldThrow />
      </ErrorBoundary>
    );
    expect(screen.getByRole("button", { name: "Reload the app" })).toBeTruthy();
  });
});
