import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { registerApp } from "./lib/pwa";
import { AppProvider } from "./lib/store";
/* Self-hosted variable fonts, replacing three `fonts.googleapis.com` requests
   that cost two extra connections before first paint, told a third party about
   every listener, and were sometimes blocked outright by a webview. Each family
   ships as unicode-range subsets, so a launch still downloads one file per
   family — the same files a CDN would have served, from our own origin. */
import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/inter-tight";
import "@fontsource-variable/jetbrains-mono";
import "./styles.css";

const container = document.getElementById("root");
if (!container) throw new Error("#root missing from index.html");

// Offline shell + installable icon set. Registration is a no-op outside a
// secure, production context, so local development is unaffected.
registerApp(() => window.dispatchEvent(new Event("vyron:update-ready")));

createRoot(container).render(
  <StrictMode>
    <ErrorBoundary full>
      <AppProvider>
        <App />
      </AppProvider>
    </ErrorBoundary>
  </StrictMode>
);
