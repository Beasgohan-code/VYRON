import { useEffect, useRef, useState } from "react";
import { useApp } from "../lib/store";

/**
 * The boot experience.
 *
 * Three real stages, not a fake timer: the shell is up as soon as React
 * mounts, the session is confirmed once `/api/state` answers, and the library
 * is warm once `/api/home` lands.
 *
 * A free Render instance can sleep, and the first request then takes 30–50 s.
 * The screen therefore never pretends to be stuck at 44%: after a few seconds
 * it says the deployment is starting, offers a retry, and always gets out of
 * the way — the app behind it already knows how to show an offline notice.
 */
type Stage = {
  key: string;
  label: string;
  done: boolean;
  note: string;
};

const WAKE_HINT_AFTER = 7; // seconds before we admit the server is starting
const RETRY_AFTER = 13;
const GIVE_UP_AFTER = 32;

export function BootScreen() {
  const { access, state, home, refreshState } = useApp();
  const [visible, setVisible] = useState(true);
  const [leaving, setLeaving] = useState(false);
  const [progress, setProgress] = useState(6);
  const [floor, setFloor] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [retrying, setRetrying] = useState(false);
  const started = useRef(Date.now());

  const sessionDone = access !== "offline" && Boolean(state);
  const libraryDone = home !== null;
  const settled = access === "locked" || access === "offline";

  /* a gentle floor so the screen never flashes past in 40 ms */
  useEffect(() => {
    const timer = window.setInterval(() => {
      setFloor((value) => Math.min(92, value + (value < 40 ? 9 : value < 70 ? 4 : 1.5)));
    }, 120);
    return () => window.clearInterval(timer);
  }, []);

  /* a one-second clock drives the honest "still starting" copy */
  useEffect(() => {
    const timer = window.setInterval(() => {
      setElapsed(Math.round((Date.now() - started.current) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const target = libraryDone ? 100 : sessionDone ? 82 : settled ? 70 : 44;
    setProgress((value) => Math.max(value, target));
  }, [libraryDone, sessionDone, settled]);

  // `locked` and `offline` have nothing left to load: the gate/notice is the
  // destination, so the overlay must not sit on top of them.
  const ready =
    settled ||
    (sessionDone && (libraryDone || elapsed >= 8)) ||
    elapsed >= GIVE_UP_AFTER;

  useEffect(() => {
    if (!ready) return;
    setProgress(100);
    const hold = window.setTimeout(() => setLeaving(true), 360);
    const gone = window.setTimeout(() => setVisible(false), 1080);
    return () => {
      window.clearTimeout(hold);
      window.clearTimeout(gone);
    };
  }, [ready]);

  const retry = async () => {
    setRetrying(true);
    started.current = Date.now();
    setElapsed(0);
    await refreshState();
    setRetrying(false);
  };

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
      note: sessionDone
        ? "verified"
        : access === "offline"
          ? "offline"
          : elapsed >= WAKE_HINT_AFTER
            ? "server starting…"
            : "checking…",
      done: sessionDone,
    },
    {
      key: "library",
      label: "Your library",
      note: libraryDone ? "synced" : sessionDone ? "loading…" : "waiting",
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

        {!ready && elapsed >= WAKE_HINT_AFTER && (
          <p className="boot-hint">
            Waking the deployment. A sleeping instance takes 30–50 seconds on its
            first request — the music starts right after.
          </p>
        )}
        {!ready && elapsed >= RETRY_AFTER && (
          <button type="button" className="boot-retry" onClick={() => void retry()} disabled={retrying}>
            {retrying ? "Checking…" : "Retry now"}
          </button>
        )}
      </div>

      <p className="boot-foot">
        {state?.bot ? `@${state.bot}` : "voice-chat music bot"}
        {state?.version ? ` · v${state.version}` : ""}
      </p>
    </div>
  );
}
