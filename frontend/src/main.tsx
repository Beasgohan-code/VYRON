import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { registerApp } from "./lib/pwa";
import { AppProvider } from "./lib/store";
import "./styles.css";

const container = document.getElementById("root");
if (!container) throw new Error("#root missing from index.html");

// Offline shell + installable icon set. Registration is a no-op outside a
// secure, production context, so local development is unaffected.
registerApp(() => window.dispatchEvent(new Event("vyron:update-ready")));

createRoot(container).render(
  <StrictMode>
    <AppProvider>
      <App />
    </AppProvider>
  </StrictMode>
);
