import { useEffect, useState } from "react";
import { applyTheme, readThemePreference, saveTheme, systemTheme, THEME_KEY, type Theme } from "./theme";

export function useTheme() {
  const [preference, setPreference] = useState<Theme | null>(readThemePreference);
  const [system, setSystem] = useState<Theme>(systemTheme);
  const theme = preference ?? system;

  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const updateSystem = () => setSystem(systemTheme());
    const updatePreference = (event: StorageEvent) => {
      if (event.key === THEME_KEY || event.key === null) setPreference(readThemePreference());
    };
    media?.addEventListener("change", updateSystem);
    window.addEventListener("storage", updatePreference);
    return () => {
      media?.removeEventListener("change", updateSystem);
      window.removeEventListener("storage", updatePreference);
    };
  }, []);

  useEffect(() => { applyTheme(theme); }, [theme]);

  return {
    theme,
    toggleTheme: () => {
      const next = theme === "dark" ? "light" : "dark";
      applyTheme(next);
      setPreference(next);
      saveTheme(next);
    },
  };
}
