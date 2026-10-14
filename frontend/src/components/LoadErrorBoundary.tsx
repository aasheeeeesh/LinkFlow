import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Shows a recoverable message instead of a blank page when part of the app fails to load or render,
 * for example a code chunk removed by a newer build that a cached page still asks for.
 */
export class LoadErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Linkflow Lab could not show this part of the page", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    const chunk = /dynamically imported module|Loading chunk|Importing a module script failed/i.test(this.state.error.message);
    return (
      <div className="note" role="alert">
        <p style={{ marginTop: 0 }}>
          {chunk
            ? "Part of Linkflow Lab could not be loaded, most likely because the site was updated since this page was opened."
            : `This part of the page could not be shown: ${this.state.error.message}`}
        </p>
        <button type="button" className="primary" onClick={() => window.location.reload()}>
          Reload the page
        </button>
      </div>
    );
  }
}
