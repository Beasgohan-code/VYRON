import { ArrowUpRight, Lock, RefreshCw, ServerCrash } from "lucide-react";
import { useApp } from "../lib/store";
import { telegram } from "../lib/api";

/**
 * SessionGate — shown when the app has no usable session.
 *
 * The old build covered this with fake data, which is why a browser preview
 * looked "working" while nothing could actually play. Here the app says what
 * is wrong and what to do about it: open it from Telegram, or retry when the
 * server is unreachable.
 */
export function SessionGate() {
  const { access, refreshState, state } = useApp();
  if (access === "ok") return null;

  const locked = access === "locked";
  const botUrl = state?.bot ? `https://t.me/${state.bot}` : "https://t.me/VyronMusicBot";
  const inside = Boolean(telegram()?.initData);

  return (
    <div className="session-gate" role="status">
      <span className={`gate-icon ${locked ? "locked" : "offline"}`}>
        {locked ? <Lock size={18} /> : <ServerCrash size={18} />}
      </span>
      <div className="gate-copy">
        <b>{locked ? "Open this from Telegram" : "Cannot reach the server"}</b>
        <p>
          {locked
            ? inside
              ? "Your session expired — reopen the app from the bot's menu button."
              : "This player is a Telegram Mini App. Music, queue and lyrics unlock when it is opened from the bot, or with an owner link."
            : "The bot answered with an error. If it is just waking up, retry in a moment."}
        </p>
      </div>
      <div className="gate-actions">
        <button type="button" className="pill-btn ghost" onClick={() => void refreshState()}>
          <RefreshCw size={13} /> Retry
        </button>
        {locked && (
          <a className="pill-btn accent" href={botUrl} target="_blank" rel="noreferrer">
            Open the bot <ArrowUpRight size={13} />
          </a>
        )}
      </div>
    </div>
  );
}
