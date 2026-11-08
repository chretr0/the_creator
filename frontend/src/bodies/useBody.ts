import { useCallback, useEffect, useState } from "react";
import { isBodyId, type BodyId } from "./index";

export const BODY_KEY = "newworlds:body";
const BODY_PARAM = "body";

function readUrlBody(): BodyId | null {
  try {
    const value = new URLSearchParams(window.location.search).get(BODY_PARAM);
    return isBodyId(value) ? value : null;
  } catch {
    return null;
  }
}

function readStoredBody(): BodyId | null {
  try {
    const value = localStorage.getItem(BODY_KEY);
    return isBodyId(value) ? value : null;
  } catch {
    return null;
  }
}

/** `?body=moon` (a shared link) wins on first load, then the last body used, then Earth. */
function initialBody(): BodyId {
  return readUrlBody() ?? readStoredBody() ?? "earth";
}

/** The body on screen, remembered across reloads (localStorage "newworlds:body"). */
export function useBody(): [BodyId, (id: BodyId) => void] {
  const [body, setBody] = useState<BodyId>(initialBody);

  useEffect(() => {
    try {
      localStorage.setItem(BODY_KEY, body);
    } catch {
      // Keep the switch usable when browser storage is unavailable.
    }
    // A `?body=` link stays in the address bar: keep it in step so a reload shows the same body.
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.has(BODY_PARAM) && url.searchParams.get(BODY_PARAM) !== body) {
        url.searchParams.set(BODY_PARAM, body);
        window.history.replaceState(window.history.state, "", url);
      }
    } catch {
      /* history unavailable */
    }
  }, [body]);

  const choose = useCallback((id: BodyId) => setBody(id), []);
  return [body, choose];
}
