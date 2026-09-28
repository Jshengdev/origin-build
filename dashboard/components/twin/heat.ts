/**
 * Heat ramp binning for the occupancy grid. A cell is colored by the hit count the API served;
 * the bins are fixed display constants, not values derived from the data. Cells under the served
 * `threshold` are not drawn.
 */
export const HEAT_BINS = [
  { from: 8, token: "--heat-warm" },
  { from: 16, token: "--heat-hot" },
  { from: 28, token: "--heat-peak" },
] as const;
export const HEAT_FLOOR_TOKEN = "--heat-cold";

export function heatToken(count: number): string {
  let token: string = HEAT_FLOOR_TOKEN;
  for (const b of HEAT_BINS) if (count >= b.from) token = b.token;
  return token;
}

/** The one depth ramp for everything with a served height: the live scan's z_m, memory's and the floor plan's tops. */
export const LIDAR_TOKENS = ["--lidar-0", "--lidar-1", "--lidar-2", "--lidar-3"] as const;
/** The served heights' span in metres, over every list given; null when none is served (never a guessed range). */
export function heightSpan(...lists: Array<ReadonlyArray<number | null> | undefined>): [number, number] | null {
  let lo = Infinity, hi = -Infinity;
  for (const l of lists) for (const v of l ?? []) if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  return lo <= hi ? [lo, hi] : null;
}
/** Where a served height sits on the ramp, 0..1 over the served span (a single height sits mid-ramp). */
export const rampT = (v: number, [lo, hi]: [number, number]) => (hi > lo ? Math.min(1, Math.max(0, (v - lo) / (hi - lo))) : 0.5);
/** The ramp's colour at t for SVG and HTML: the two neighbouring tokens mixed. */
export function rampCss(t: number) {
  const u = t * (LIDAR_TOKENS.length - 1), i = Math.min(LIDAR_TOKENS.length - 2, Math.floor(u));
  return `color-mix(in srgb, var(${LIDAR_TOKENS[i + 1]}) ${Math.round((u - i) * 100)}%, var(${LIDAR_TOKENS[i]}))`;
}

/** Ink on the map. The map is dark in both themes, so this does not follow the page's ink. */
export const MAP_INK = "#EDEDE7";
export const MAP_INK_MUTED = "#A2A39C";
/** Red on the map: the dark theme's signal-alert in both themes (the light one, #A5342A, is 2.5:1 on the canvas; this is 7:1). */
export const MAP_ALERT = "#F28B7F";
