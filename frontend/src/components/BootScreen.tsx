import { useEffect, useRef, useState } from "react";
import { useApp } from "../lib/store";

/**
 * The boot experience.
 *
 * Three real stages, not a fake timer: the shell is up as soon as React
 * mounts, the session is confirmed once `/api/state` answers, and the library
 * is warm once `/api/home` lands. Every stage completes from actual state, so
 * a slow deployment shows an honest "still connecting…" instead of a lie.
 */
type Stage = {
  key: string;
  label: string;
  done: boolean;
  note: string;
};

export function BootScreen() {
  const { access, state, home } = useApp();
  const [visible, setVisible] = useState(true);
  const [leaving, setLeaving] = useState(false);
  const [progress, setProgress] = useState(6);
  const [floor, setFloor] = useState(0);
  const started = useRef(Date.now());

  const sessionDone = access !== "offline" && Boolean(state);
  const libraryDone = home !== null;

  /* a gentle floor so the screen never flashes past in 40 ms */
  useEffect(() => {
    const timer = window.setInterval(() => {
      setFloor((value) => Math.min(92, value + (value < 40 ? 9 : value < 70 ? 4 : 1.5)));
    }, 120);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const target = libraryDone ? 100 : sessionDone ? 82 : 44;
    setProgress((value) => Math.max(value, target));
  }, [libraryDone, sessionDone]);

  const ready = (sessionDone || access === "locked") && (libraryDone || Date.now() - started.current > 6000);

  useEffect(() => {
    if (!ready) return;
    setProgress(100);
    const hold = window.setTimeout(() => setLeaving(true), 420);
    const gone = window.setTimeout(() => setVisible(false), 1180);
    return () => {
      window.clearTimeout(hold);
      window.clearTimeout(gone);
    };
  }, [ready]);

  if (!visible) return null;

  const shown = Math.round(Math.max(progress, floor));
  const stages: Stage[] = [
    {
      key: "shell",
      label: "Interface",
      note: "ready",
      done: true,
    },
    {
      key: "session",
      label: "Telegram session",
      note: sessionDone ? "verified" : access === "offline" ? "offline" : "checking…",
      done: sessionDone,
    },
    {
      key: "library",
      label: "Your library",
      note: libraryDone ? "synced" : "loading…",
      done: libraryDone,
    },
  ];

  return (
    <div className={`boot-screen ${leaving ? "leaving" : ""}`} role="status" aria-live="polite">
      <div className="boot-art" aria-hidden="true" />
      <div className="boot-veil" aria-hidden="true" />

      <div className="boot-body">
        <div className="boot-logo">
          <img src="/brand/avatar.jpg" alt="" />
          <span>{shown}%</span>
        </div>

        <div className="boot-title">
          <h1>VYRON</h1>
          <p>music beyond limits</p>
        </div>

        <div className="boot-track" aria-hidden="true">
          <span style={{ width: `${shown}%` }} />
        </div>

        <ul className="boot-stages">
          {stages.map((stage) => (
            <li key={stage.key} className={stage.done ? "done" : ""}>
              <i />
              <b>{stage.label}</b>
              <em>{stage.note}</em>
            </li>
          ))}
        </ul>
      </div>

      <p className="boot-foot">
        {state?.bot ? `@${state.bot}` : "voice-chat music bot"} · v{state?.version ?? "1.3.0"}
      </p>
    </div>
  );
}
