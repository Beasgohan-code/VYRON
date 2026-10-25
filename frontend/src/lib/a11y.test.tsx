import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it } from "vitest";
import { useFocusTrap } from "./a11y";

function Dialog({ open }: { open: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, open);
  if (!open) return null;
  return (
    <div ref={ref} role="dialog" aria-modal="true" aria-label="A dialog">
      <button type="button">first</button>
      <button type="button">last</button>
    </div>
  );
}

describe("focus trap", () => {
  it("moves focus into the dialog when it opens", () => {
    render(<Dialog open />);
    expect(document.activeElement).toBe(screen.getByText("first"));
  });

  it("sends focus back to whatever had it when it closes", () => {
    const opener = document.createElement("button");
    opener.textContent = "open";
    document.body.appendChild(opener);
    opener.focus();

    const { rerender } = render(<Dialog open />);
    expect(document.activeElement).not.toBe(opener);

    rerender(<Dialog open={false} />);
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("wraps Tab inside the dialog instead of walking into the page", () => {
    render(<Dialog open />);
    const first = screen.getByText("first");
    const last = screen.getByText("last");

    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(first);

    first.focus();
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("does not steal focus while it is closed", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    render(<Dialog open={false} />);
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("focuses the dialog itself when it has no controls", () => {
    function Empty({ open }: { open: boolean }) {
      const ref = useRef<HTMLDivElement>(null);
      useFocusTrap(ref, open);
      return (
        <div ref={ref} role="dialog" aria-label="Empty">
          nothing to tab to
        </div>
      );
    }
    const { container } = render(<Empty open />);
    act(() => {
      /* the hook focuses on mount */
    });
    expect(document.activeElement).toBe(container.querySelector('[role="dialog"]'));
  });
});
