import { AlertTriangle } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Shown instead of the default copy, e.g. "the player". */
  where?: string;
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
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // The owner console reads this from the journal on the server side; here it
    // is only what a developer can paste into an issue.
    console.error("view crashed", error, info.componentStack);
  }

  private reset = (): void => this.setState({ error: null });

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <section className="crash" role="alert">
        <span className="crash-icon">
          <AlertTriangle size={22} />
        </span>
        <h2>This screen stopped working</h2>
        <p>
          {this.props.where ? `The ${this.props.where} hit an error.` : "Something in this view threw."}{" "}
          Your music keeps playing — try again.
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
