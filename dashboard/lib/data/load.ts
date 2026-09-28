import type { DataSource } from "./data-source";

/** Everything the TwinMap draws, loaded in one go. */
export async function loadMap(ds: DataSource) {
  const [grid, floorPlan, zones, routes, stops, devices, looks] = await Promise.all([
    ds.getGrid(), ds.getFloorPlan(), ds.getZones(), ds.getRoutes(), ds.getStops(), ds.getDevices(), ds.getLooks(),
  ]);
  return { grid, floorPlan, zones, routes, stops, devices, looks };
}
export type MapData = Awaited<ReturnType<typeof loadMap>>;
