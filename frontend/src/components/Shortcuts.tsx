import { Keyboard, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { SHORTCUTS } from "../lib/keys";

/**
 * The keyboard cheat-sheet.
 *
 * The app is phone-first, but it also runs in Telegram Web and in a plain
 * browser tab, and on a desktop the space bar is the first thing anyone tries.
 * Rather than describing the keys in prose somewhere nobody reads, `?` opens
 * this — and it is generated from the same table the handler uses, so it can
 * never drift.
 */
export function Shortcuts({ open, onClose }: { open: boolean; onClose: () => void }) {
  const close = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    close.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="scrim"
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="sheet shortcuts">
        <span className="grabber" aria-hidden="true" />
        <div className="sheet-head">
          <h3>
            <Keyboard size={16} /> Shortcuts
          </h3>
          <button ref={close} type="button" className="btn-icon" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <div className="sheet-body">
          <ul className="shortcut-list">
            {SHORTCUTS.map((shortcut) => (
              <li key={shortcut.id}>
                <span>{shortcut.label}</span>
                <span className="keys">
                  {shortcut.keys.map((key) => (
                    <kbd key={key}>{key}</kbd>
                  ))}
                </span>
              </li>
            ))}
          </ul>
          <p className="shortcut-note">
            Shortcuts stay out of the way while you are typing — except <kbd>Esc</kbd>.
          </p>
        </div>
      </div>
    </div>
  );
}
