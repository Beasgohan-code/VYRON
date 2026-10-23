import { Keyboard, X } from "lucide-react";
import { useEffect } from "react";

const GROUPS: { title: string; rows: [string, string][] }[] = [
  {
    title: "Navigate",
    rows: [
      ["⌘ K / Ctrl K", "Command palette"],
      ["/", "Focus search"],
      ["?", "This cheat sheet"],
      ["Esc", "Close player / sheet"],
    ],
  },
  {
    title: "Playback",
    rows: [
      ["Space", "Play or pause"],
      ["← / →", "Seek 5 seconds"],
      ["N", "Next track"],
      ["M", "Mute / unmute"],
    ],
  },
];

export function ShortcutSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="sheet-backdrop" onClick={onClose} role="presentation">
      <div
        className="shortcut-sheet"
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sheet-head">
          <h2>
            <Keyboard size={15} /> Keyboard shortcuts
          </h2>
          <button type="button" className="icon-btn" aria-label="Close shortcuts" onClick={onClose}>
            <X size={15} />
          </button>
        </div>
        <div className="sheet-groups">
          {GROUPS.map((group) => (
            <div key={group.title} className="sheet-group">
              <span className="sheet-title">{group.title}</span>
              {group.rows.map(([keys, action]) => (
                <div key={keys} className="sheet-row">
                  <kbd>{keys}</kbd>
                  <span>{action}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
        <p className="muted small">Shortcuts are ignored while you type in a field.</p>
      </div>
    </div>
  );
}
