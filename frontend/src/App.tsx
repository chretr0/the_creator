import { useBody } from "./bodies/useBody";
import EarthApp from "./earth/EarthApp";
import MoonApp from "./moon/MoonApp";

/**
 * Shell: one workspace per body. Switching remounts the whole app, so nothing Earth-specific (layers,
 * regional data, scenarios) is ever fetched for Moon coordinates, and each map starts on its own body.
 */
export default function App() {
  const [bodyId, setBodyId] = useBody();
  return bodyId === "moon" ? <MoonApp onBody={setBodyId} /> : <EarthApp onBody={setBodyId} />;
}
