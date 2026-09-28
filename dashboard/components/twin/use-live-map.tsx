"use client";
/**
 * The live map, shared by Overview and Paths: every TwinMap layer polled from the wtdd API (lib/data/api.ts) and shaped
 * into TwinMap's props, in the house frame's pixels as served. Paths passes its unsaved edit as `draft`; the path, the
 * stops and the zones are then drawn from it instead of GET /map.
 *
 * A route that fails shows FAILED and its reason on the map's bottom lines; nothing falls back to a fixture.
 */
import { useState } from "react";
import { usePoll, type BlobsPx, type DogState, type FloorPlanPx, type GridPx, type LidarPx, type MapJson, type ObjectsPx, type Scale } from "@/lib/data/api";
import type { Device, FloorPlan, Route, Stop, Zone } from "@/lib/data";
import type { LiveLayers, TwinMapProps } from "./twin-map";
import { MAP_INK, MAP_INK_MUTED } from "./heat";

/** The map space: house.svg's viewBox, as ui/map.json's note says ("Map space = house.svg viewBox (0 0 1060 1540)"). */
const FRAME: [number, number, number, number] = [0, 0, 1060, 1540];
/** The Go2's body, 0.70 x 0.31 m (S9); drawn at the served px_per_m. */
const BODY_M = { length: 0.7, width: 0.31 };
/** Display constant for "the dog's state is fresh", the old remote's (ui/index.html: age_ms < 2000). */
export const FRESH_MS = 2000;
const LOOK_NAME: Record<string, Stop["look"]> = { tilt: "nod", level: "level", sit: "sit" };

/**
 * `floorPlanButton`: the page has the Floor plan press (Overview); without it, a served "or press floor plan" is dropped.
 * `saved`: the map as this page just saved it (with the _version the save returned), drawn until the poll serves that
 * version or a newer one, so a save does not flicker back to the older map for a poll.
 */
export function useLiveMap(draft?: MapJson | null, floorPlanButton = true, saved?: MapJson | null) {
  // `refresh` reads the pose, the scale and everything drawn from them now, not at the next poll: after a calibrate or a
  // scale POST the API re-projects the grid, the floor plan and the scan, and the dog's outline takes the new scale
  const [kick, setKick] = useState(0);
  const dog = usePoll<DogState>("/dog/state", 1000, kick);
  const d = dog.data;
  const grid = usePoll<GridPx>("/dog/grid", 2000, kick);
  const plan = usePoll<FloorPlanPx>("/dog/floorplan", 2000, kick);
  const objects = usePoll<ObjectsPx>("/dog/objects", 2000);
  const blobs = usePoll<BlobsPx>("/dog/blobs", 2000);
  const lidar = usePoll<LidarPx>(d?.connected ? "/dog/lidar" : null, 500, kick);
  const scale = usePoll<Scale>("/dog/scale", 10000, kick);
  const map = usePoll<MapJson>("/map", 3000);

  const follow = d?.follow ?? {};
  const fresh = !!d?.connected && d.state?.age_ms != null && d.state.age_ms < FRESH_MS;
  const walking = !!follow.active;

  // <=: a second save in the same second gets the same _version, so a poll between the two must not win
  const served = saved && (map.data?._version ?? 0) <= (saved._version ?? 0) ? saved : map.data;
  const props = shapeLive({
    map: draft ?? served, grid: grid.data, plan: plan.data, objects: objects.data, blobs: blobs.data, lidar: lidar.data, pxPerM: scale.data?.px_per_m,
    dog: d, fresh, house: "/api/house.svg",
    status: (follow.planned?.length ?? 0) > 0 ? <RouteKey /> : undefined,
  });
  // Johnny: "the sitemap has to be in its own box with the depth map instruction legend and that's it": the map keeps its
  // legend; each layer's served status and every FAILED is the page's to show, outside the map, never dropped
  const notes = <MapStatus map={map} scale={scale} blobs={blobs} grid={grid} plan={plan} objects={objects} lidar={lidar} connected={!!d?.connected} press={floorPlanButton} />;
  return { dog, lidar, scale, map, served, fresh, walking, follow, props, notes, refresh: () => setKick((k) => k + 1) };
}

/** Each grid cell's served top: the floor plan's class_top_m for the cell at the same served position (the grid and the
 *  floor plan share one lattice); null where the floor plan has none. Undefined when no tops are served. Kept per pair of
 *  responses, so a render between polls does not join again. */
const topsSeen = new WeakMap<GridPx, { f: FloorPlanPx; tops: Array<number | null> }>();
function cellTops(g: GridPx, f?: FloorPlanPx) {
  if (!f?.class_top_m) return undefined;
  const seen = topsSeen.get(g);
  if (seen?.f === f) return seen.tops;
  const at = new Map<string, number | null>();
  for (const [cls, pts] of Object.entries(f.class_px)) pts.forEach(([x, y], i) => at.set(`${x},${y}`, f.class_top_m![cls]?.[i] ?? null));
  const tops = g.cells_px.map(([x, y]) => at.get(`${x},${y}`) ?? null);
  topsSeen.set(g, { f, tops });
  return tops;
}

/** Served responses → TwinMap's props, with no request of its own: the hook's shaping, and the Storybook stories' on a fixture frame. */
export function shapeLive(x: {
  map?: MapJson | null; grid?: GridPx; plan?: FloorPlanPx; objects?: ObjectsPx; blobs?: BlobsPx; lidar?: LidarPx; pxPerM?: number;
  dog?: DogState; fresh?: boolean; house?: string; status?: React.ReactNode;
}): Pick<TwinMapProps, "live" | "zones" | "routes" | "stops" | "devices" | "runActive" | "floorPlan"> {
  const m = x.map, g = x.grid, f = x.plan, px = x.pxPerM, d = x.dog, follow = d?.follow ?? {};
  const path = m?.path ?? [];
  const live: LiveLayers = {
    frame: FRAME,
    house: x.house,
    lamps: (m?.lights ?? []).map((l) => ({ id: l.id, label: l.label ?? l.name ?? l.id, kind: l.kind, pts: l.pts })),
    waypoints: path,
    rooms: m?.rooms,
    cells: g?.cell_px ? { cells: g.cells_px, cell: g.cell_px, hits: g.hits, threshold: g.threshold, tops: cellTops(g, f) } : undefined,
    scan: x.lidar?.points_px,
    scanZ: x.lidar?.z_m,
    tie: d?.cal?.map,
    scanKnown: x.lidar?.known,
    scanWhy: !d?.connected ? "the dog is not connected" : x.lidar && !x.lidar.on ? "the LiDAR is off" : x.lidar?.why,
    pxPerM: px,
    heights: f?.segments_top_m ? { segments: f.segments_top_m, classes: f.class_top_m ?? {} } : null,
    classCells: f?.cell_px ? { cell: f.cell_px, byClass: f.class_px } : undefined,
    planned: follow.planned,
    trace: follow.trace,
    pill: px ? { length: BODY_M.length * px, width: BODY_M.width * px } : undefined,
    objects: x.objects?.objects.filter((o) => o.pos_px).map((o) => ({
      id: o.id, label: o.label, p: o.p, position: o.pos_px!, stale: o.stale,
      message: o.message ? `${o.message}${o.message_source === "stub" ? " · stand-in" : ""}` : o.message,   // a stub-drafted line never reads as live
    })),
    // Jev's name for each run or blob, where it is, as served; a failed call is a red line on its place, never a guess
    jev: x.blobs?.labels.filter((l) => l.pos_px).map((l) => ({
      id: l.blob_id, position: l.pos_px!, error: l.error,
      text: l.error ? `${l.kind} ${l.blob_id} · FAILED` : `${l.label} · ${l.p != null ? l.p.toFixed(2) : "no p"}${l.source === "fixture" || l.source === "stub" ? " · stand-in" : ""}`,
    })),
    status: x.status,
  };
  const floorPlan: FloorPlan | undefined = f?.segments_px.length
    ? { segments: f.segments_px.map((r) => [r[0], r[1], r[2], r[3]] as [number, number, number, number]), classes: f.classes, constantsVerified: false } : undefined;
  const zones: Zone[] = (m?.zones ?? []).filter((z) => z.nogo === true)
    .map((z) => ({ id: z.name, name: zoneName(z), kind: "nogo", polygon: z.poly, drawnBy: z.by === "auto" ? "dog" : "person", status: "rule" }));
  const routes: Route[] = path.length > 1 ? [{ id: "path", name: "The drawn path", source: "GET /map", status: "exists_on_main", polyline: path }] : [];
  const stops: Stop[] = (m?.stops ?? []).map((i, n) => ({ id: `stop-${i}`, index: n + 1, name: `Stop ${n + 1}`, position: path[i], look: LOOK_NAME[m?.actions?.[i]?.look ?? ""] }))
    .filter((s) => s.position);
  const devices: Device[] = d?.map ? [{
    id: "go2", kind: "body", name: "Go2", integration: "GET /dog/state", position: d.map.p, headingDeg: d.map.heading_deg,
    status: d.connected ? (x.fresh ? "online" : "stale") : "offline",
  }] : [];
  return { live, zones, routes, stops, devices, runActive: !!follow.active, floorPlan };
}

/**
 * A zone's words, as today's remote writes them: 19's auto zone "auto · chair · 0.84", one a person confirmed "table ·
 * 0.71 · scout · confirmed by Sam", a drawn one its label. A stand-in (app "stub", DEMO_CACHE) says so.
 */
export function zoneName(z: NonNullable<MapJson["zones"]>[number]) {
  const tail = z.app === "stub" ? " · stand-in" : "";
  if (z.by === "auto") return `auto · ${z.label} · ${z.p != null ? z.p.toFixed(2) : "no p served"}${tail}`;
  if (z.source === "scout" && z.by) return `${z.label ?? z.name} · confirmed by ${z.by}${tail}`;
  return `${z.label ?? z.name}${tail}`;
}

/**
 * Bottom left of the map, only what a person needs: a layer that failed (red, with its reason), a layer that is empty
 * and why, a shortcut (objects served from a fixture file, DEMO_CACHE), and the planned / actual key while walking.
 * Counts and file names stay in the receipts' rows, not on the map.
 */
function MapStatus({ map, scale, blobs, grid, plan, objects, lidar, connected, press }: {
  map: { error?: string }; scale: { error?: string }; blobs: { data?: BlobsPx; error?: string }; grid: { data?: GridPx; error?: string }; plan: { data?: FloorPlanPx; error?: string };
  objects: { data?: ObjectsPx; error?: string }; lidar: { data?: LidarPx; error?: string }; connected: boolean; press: boolean;
}) {
  const bad = (what: string, e: string) => <span className="text-signal-alert">{e.startsWith(what) ? `FAILED ${e}` : `${what} · FAILED ${e}`}</span>;
  const words = (why: string) => why.replace(/\s*\((?:GET|POST) [^)]*\)/g, "");   // a served reason names its route; the button beside it already says it
  const fp = (why: string) => (press ? words(why) : words(why).replace(/,? or press floor plan.*$/i, ""));   // no Floor plan button on this page
  const g = grid.data, f = plan.data, o = objects.data, l = lidar.data;
  return (
    <>
      {map.error && bad("map", map.error)}
      {scale.error && bad("scale", `${scale.error} · the dog's outline is not drawn`)}
      {grid.error ? bad("grid", grid.error) : g?.why ? <span>grid · {words(g.why)}</span> : g?.cb_errors ? bad("grid", `to take ${g.cb_errors} frames`) : null}
      {plan.error ? bad("floor plan", plan.error) : f?.why ? (f.ok === false ? bad("floor plan", fp(f.why)) : <span>floor plan · {fp(f.why)}</span>) : null}
      {objects.error ? bad("objects", objects.error) : o?.why ? <span>objects · {o.why}</span> : null}
      {o?.source?.startsWith("fixture") && <span>objects · served from a fixture file, not seen tonight</span>}
      {blobs.error ? bad("names", blobs.error) : blobs.data?.source?.startsWith("fixture") && <span>names · served from a fixture file, not seen tonight</span>}
      {lidar.error ? bad("live scan", lidar.error) : connected && l?.why ? <span>live scan · {l.why}</span> : null}
    </>
  );
}

/** The route's key, in the map's legend while a walk has planned legs. */
function RouteKey() {
  return (
    <span className="flex items-center gap-1.5"><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke={MAP_INK_MUTED} strokeWidth="1.5" /></svg>drawn
      <svg width="22" height="6" className="ml-2"><line x1="0" y1="3" x2="22" y2="3" stroke={MAP_INK} strokeWidth="1.5" strokeDasharray="6 5" /></svg>planned
      <svg width="22" height="6" className="ml-2"><line x1="0" y1="3" x2="22" y2="3" stroke={MAP_INK} strokeWidth="2.5" /></svg>actual</span>
  );
}
