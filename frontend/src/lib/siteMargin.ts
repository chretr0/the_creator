import type { SiteResource } from "./buildings";

/** Only like-for-like resource quantities may be subtracted. Missing is never zero. */
export function siteMargin(resource: SiteResource): number | null {
  if (resource.status || resource.available === null || resource.needed === null) return null;
  const margin = resource.available - resource.needed;
  return Number.isFinite(margin) ? margin : null;
}
