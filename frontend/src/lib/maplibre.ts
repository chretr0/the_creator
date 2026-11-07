/**
 * MapLibre 6 locates its web worker relative to its own module URL, which breaks once Vite
 * pre-bundles or bundles the library. Point it at a Vite-built worker explicitly
 * (see the worker note in the OpenFreeMap / MapLibre quick start).
 */
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

maplibregl.setWorkerUrl(workerUrl);

export { maplibregl };
