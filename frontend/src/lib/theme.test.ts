import { afterEach, describe, expect, it, vi } from "vitest";
import { readThemePreference, saveTheme, systemTheme, THEME_KEY } from "./theme";

afterEach(() => { vi.unstubAllGlobals(); });

describe("theme preferences", () => {
  it("persists an explicit choice and reads it back", () => {
    const storage = new Map<string, string>();
    vi.stubGlobal("localStorage", { getItem: (key: string) => storage.get(key), setItem: (key: string, value: string) => storage.set(key, value) });
    expect(readThemePreference()).toBeNull();
    saveTheme("dark");
    expect(readThemePreference()).toBe("dark");
    saveTheme("light");
    expect(storage.get(THEME_KEY)).toBe("light");
    expect(readThemePreference()).toBe("light");
  });

  it("ignores corrupt or obsolete preferences so the system setting can be used", () => {
    vi.stubGlobal("localStorage", { getItem: () => "other" });
    vi.stubGlobal("window", { matchMedia: () => ({ matches: true }) });
    expect(readThemePreference() ?? systemTheme()).toBe("dark");
  });

  it("still works when storage is blocked", () => {
    const blocked = () => { throw new Error("Storage blocked"); };
    vi.stubGlobal("localStorage", { getItem: blocked, setItem: blocked });
    vi.stubGlobal("window", { matchMedia: () => ({ matches: false }) });
    expect(() => saveTheme("dark")).not.toThrow();
    expect(readThemePreference() ?? systemTheme()).toBe("light");
  });
});
