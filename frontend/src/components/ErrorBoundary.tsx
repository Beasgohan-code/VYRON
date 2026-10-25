import { AlertTriangle } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { reportCrash } from "../lib/api";

interface Props {
  children: ReactNode;
  /** Shown instead of the default copy, e.g. "the player". */
  where?: string;
  /**
   * Root boundary: there is no shell left around it, so it fills the screen
   * instead of sitting inside the page as a pane.
   */
  full?: boolean;
}

interface State {
  error: Error | null;
}

/**
 * A crash in one view must not take the whole Mini App down.
 *
 * React unmounts the entire tree on an uncaught render error, which in a webview
 * means a white screen and no way back — not even to the login gate. This keeps
 * the shell (nav, dock, audio) alive and offers a reset for the broken pane.
 *
 * Every crash is also posted to the owner journal (`/api/client-error`). Without
 * that, the only evidence a listener can give is "it went blank", which is not
 * something anyone can fix.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("view crashed", error, info.componentStack);
    void reportCrash({
      message: error.message || "render failed",
      stack: `${error.stack ?? ""}\n\n${info.componentStack ?? ""}`.trim(),
      scope: this.props.where ? `view:${this.props.where}` : "render",
    });
  }

  private reset = (): void => this.setState({ error: null });

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <section className={`crash${this.props.full ? " crash-full" : ""}`} role="alert">
        <span className="crash-icon">
          <AlertTriangle size={22} />
        </span>
        <h2>{this.props.full ? "Something broke on this screen" : "This screen stopped working"}</h2>
        <p>
          {this.props.where ? `The ${this.props.where} hit an error.` : "Something in this view threw."}{" "}
          {this.props.full
            ? "The bot, the queue and anything the voice chat is playing are unaffected — reloading usually clears it, and the details were written to the owner's log."
            : "Your music keeps playing — try again."}
        </p>
        <code>{error.message}</code>
        <div className="crash-actions">
          <button type="button" className="btn btn-primary sm" onClick={this.reset}>
            Try again
          </button>
          <button type="button" className="btn btn-ghost sm" onClick={() => window.location.reload()}>
            Reload the app
          </button>
        </div>
      </section>
    );
  }
}
