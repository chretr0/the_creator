import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { MoonPlaceHit } from "./geo";
import MoonPlaceSearch, { MoonPlaceOptions, moveCursor, optionId, searchStatusMessage } from "./MoonPlaceSearch";

const IDLE = { loading: false, error: null, notPrepared: false };
const hit = (label: string): MoonPlaceHit => ({
  key: `place:${label}`,
  label,
  detail: "Crater · 85 km",
  lat: -43.3,
  lon: -11.36,
  beyondMap: false,
  source: "gazetteer",
});

describe("moveCursor", () => {
  it("stays at 0 when there are no rows (ArrowDown while the gazetteer loads)", () => {
    // The old Math.min(hits.length - 1, c + 1) gave -1 here, so Enter did nothing once results arrived.
    expect(moveCursor(0, 1, 0)).toBe(0);
    expect(moveCursor(0, -1, 0)).toBe(0);
  });

  it("moves within the rows and stops at both ends", () => {
    expect(moveCursor(0, 1, 3)).toBe(1);
    expect(moveCursor(2, 1, 3)).toBe(2);
    expect(moveCursor(0, -1, 3)).toBe(0);
    expect(moveCursor(5, 1, 3)).toBe(2);
  });
});

describe("MoonPlaceOptions", () => {
  const html = renderToStaticMarkup(
    <MoonPlaceOptions id="places" hits={[hit("Tycho"), hit("Tycho A")]} cursor={1} hidden={false} onPick={() => {}} />,
  );

  it("is a listbox whose children are all options with ids", () => {
    expect(html).toMatch(/^<ul id="places"[^>]*role="listbox"/);
    expect(html.match(/<li /g)).toHaveLength(2);
    expect(html.match(/role="option"/g)).toHaveLength(2);
    expect(html).toContain(`id="${optionId("places", 0)}"`);
    expect(html).toContain(`id="${optionId("places", 1)}"`);
  });

  it("marks the highlighted option and nests no buttons", () => {
    expect(html).toMatch(/id="places-option-1" role="option" aria-selected="true"/);
    expect(html).toMatch(/id="places-option-0" role="option" aria-selected="false"/);
    expect(html).not.toContain("<button");
  });
});

describe("MoonPlaceSearch", () => {
  const html = renderToStaticMarkup(<MoonPlaceSearch index={null} status={IDLE} onFocus={() => {}} onGo={() => {}} />);

  it("ties the combobox to its listbox", () => {
    const controls = /aria-controls="([^"]+)"/.exec(html)?.[1];
    expect(controls).toBeTruthy();
    expect(html).toContain(`<ul id="${controls}"`);
    expect(html).toMatch(/role="combobox"/);
  });

  it("keeps the status messages in a live region outside the listbox", () => {
    const listEnd = html.indexOf("</ul>");
    const status = html.indexOf('role="status"');
    expect(listEnd).toBeGreaterThan(-1);
    expect(status).toBeGreaterThan(listEnd);
    expect(html).toMatch(/role="status" aria-live="polite"/);
  });
});

describe("searchStatusMessage", () => {
  it("says what the list can't show", () => {
    expect(searchStatusMessage([], null, { ...IDLE, loading: true }, "ty")?.text).toBe("Loading the IAU gazetteer…");
    expect(searchStatusMessage([], [], IDLE, " zz ")?.text).toBe("No named feature matches “zz”.");
    expect(searchStatusMessage([], null, { ...IDLE, notPrepared: true, error: "503" }, "ty")).toMatchObject({ warn: true });
    expect(searchStatusMessage([], null, { ...IDLE, error: "boom" }, "ty")?.text).toBe("Couldn’t load place names: boom");
    expect(searchStatusMessage([hit("Tycho")], [], IDLE, "ty")).toBeNull();
  });
});
