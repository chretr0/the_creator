import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";
import App from "./App";
import { applyTheme, readThemePreference, systemTheme } from "./lib/theme";

// Set the palette before React paints, including on a reload with a saved preference.
applyTheme(readThemePreference() ?? systemTheme());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
