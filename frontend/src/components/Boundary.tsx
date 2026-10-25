import { Component, type ErrorInfo, type ReactNode } from "react";
import { reportCrash } from "../lib/api";

type Props = { children: ReactNode };
type State = { error: Error | null };

/**
 * The last line of defence.
 *
 * React unmounts the whole tree when a render throws, which in a Mini App means
 * a blank white rectangle inside Telegram — no message, no way back, and
 * nothing in the owner journal to explain it. This keeps the failure inside the
 * viewer's screen: a readable card, a reload, and one line in the journal with
 * the stack so the crash can actually be fixed.
 *
 * It sits above the store so a crash inside a player or a sheet cannot take the
 * navigation with it, and it never re-renders the broken child automatically —
 * only a deliberate reload clears the error.
 */
export class Boundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    void reportCrash({
      message: error.message || "render failed",
      stack: `${error.stack ?? ""}\n\n${info.componentStack ?? ""}`.trim(),
      scope: "render",
    });
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="crash">
        <div className="crash-card">
          <span className="crash-mark" aria-hidden="true">
            ⚡
          </span>
          <h1>Something broke on this screen</h1>
          <p>
            The rest of VYRON is still running — the bot, the queue and anything the voice chat is playing
            are unaffected. Reloading the app usually clears it, and the details below were written to the
            owner's log.
          </p>
          <code className="crash-detail">{error.message || "unknown error"}</code>
          <div className="row gap">
            <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
              Reload the app
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                this.setState({ error: null });
              }}
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }
}
