"use client";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useTheme } from "next-themes";
import { Camera, ChevronDown, Dog, Layers, Lightbulb, Maximize, Minus, Plus } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ActionButton } from "@/components/wtdd";
import { cn } from "@/lib/utils";
import type { Device, FloorPlan, Grid, Look, Route, Stop, Zone } from "@/lib/data";
import { Photo } from "@/components/live/photo";
import type { RunImage } from "@/lib/data/api";
import { HEAT_BINS, HEAT_FLOOR_TOKEN, LIDAR_TOKENS, MAP_ALERT, MAP_INK, MAP_INK_MUTED, heatToken, heightSpan, rampCss, rampT } from "./heat";
import { DeviceTip, MAP_TIP, MapPin } from "./map-pin";

export type LayerKey = "grid" | "floorplan" | "zones" | "route" | "stops" | "lights" | "camera" | "dog" | "pins" | "scan" | "house"
  | "heights" | "memory" | "decisions" | "plan";
type XY = [number, number];

/**
 * The live layers, straight from the wtdd API (lib/data/api.ts), every position a map pixel in the house frame as served.
 * With `live` set, the map's world unit is that pixel; nothing is converted. Shapes come only from the served points.
 */
export interface LiveLayers {
  /** The house frame's box (house.svg's viewBox): the bounds the map fits to, and where house.svg is drawn. */
  frame: [number, number, number, number];
  /** A box inside the frame to fit the first view to instead (Storybook's samples open on the furnished room). */
  fit?: [number, number, number, number];
  /** house.svg, drawn by hand: the rooms' outlines and names. On by default (Johnny, 2026-09-27: the outlines of the actual locations). */
  house?: string;
  /** GET /map lights: the lamps (a dot) and the LED strip (a line), where they were placed by hand. */
  lamps?: Array<{ id: string; label: string; kind: "dot" | "line"; pts: XY[] }>;
  /** GET /map rooms: the house plan's rooms; the one the dog is in gets a soft background (with the house plan layer). */
  rooms?: Array<{ name: string; poly: XY[] }>;
  /** GET /map path: the drawn waypoints, a dot each. */
  waypoints?: XY[];
  /** Paths: a tap on a waypoint (delete it, or make it a stop). Unset, the dots are drawn only. */
  onWaypoint?: (i: number) => void;
  /** GET /dog/grid: one square per cell centred on its served corner pixel. Without `hits` it is one ink and the heat key is hidden. */
  cells?: { cells: XY[]; cell: number; hits?: number[]; threshold: number; tops?: Array<number | null>; topsWhy?: string };
  /** GET /dog/lidar points_px: the live scan; `scanKnown` (S13) is true where that cell is already a wall in memory. */
  scan?: XY[];
  scanKnown?: boolean[];
  /** GET /dog/lidar z_m (#67): each live point's measured height in metres, for its colour on the depth ramp. */
  scanZ?: Array<number | null>;
  /** GET /dog/state cal.map (#69): the calibration tie, the point a scale change re-projects the scan about. */
  tie?: XY;
  /** Why there is no live scan, from the served state: "the dog is not connected", "the LiDAR is off", or the lidar's own why. */
  scanWhy?: string;
  /** The served scale, for drawing a served height in metres (toggle A). */
  pxPerM?: number;
  /** S13's measured tops (toggle A, 2.5D): one per floor-plan segment and per furniture cell; null when not served. */
  heights?: { segments: Array<number | null>; classes: Record<string, Array<number | null>> } | null;
  /** The floor plan's cells by class with their served positions: dithered flat (low, slab, tall), or extruded in 2.5D.
   *  The wall runs come in through `floorPlan`, as crisp lines. */
  classCells?: { cell: number; byClass: Record<string, XY[]> };
  /** GET /dog/state follow: every planned leg (dashed) and where the dog actually went (solid). */
  planned?: XY[][];
  trace?: XY[];
  /** The Go2 at its real size, 0.70 x 0.31 m in pixels at the served scale, head marked. */
  pill?: { length: number; width: number };
  /** The follower's decisions (route.decided rows), numbered oldest first, at the pose each row served (state_before.p). */
  decisions?: Array<{ n: number; position: XY; ok: boolean }>;
  /** Overview's calibration (today's remote's drag): drag the dog to where it is, drag its cone tip to where it faces;
   *  called once on release with the new pose, which the page posts as POST /dog/calibrate. */
  calibrate?: (pose: { p: XY; heading_deg: number }) => void;
  /** GET /dog/blobs: Jev's name and p for each floor-plan run or blob, at its served position (a failed call reads FAILED). */
  jev?: Array<{ id: string; position: XY; text: string; error?: string }>;
  /** GET /dog/objects: a pin per placed object, its label and p on the map. */
  objects?: Array<{ id: string; label: string; p: number; position: XY; stale?: boolean; message?: string | null }>;
  /** The map's own key lines beside its legend (the route's key while walking). Each layer's served status and FAILED are
   *  the page's to show, outside the map (useLiveMap's `notes`). */
  status?: React.ReactNode;
  /** GET /field while a lights walk runs: the field's point, its radius in map px, and each light's served level (0-100). */
  field?: { p: XY; radius: number; levels: Record<string, number> };
  /** Each no-go zone's words and, for an auto zone, the scout's photo of it (by zone id): shown only in the hover card,
   *  never on the map (Johnny: "when you hover over it it shows an image of what it sees ... it doesn't show on the map"). */
  zoneInfo?: Record<string, { what: string; photo?: RunImage }>;
  /** Calibrate's "scale by a wall" (Johnny: "to scale it, i can grab the wall and align it to a drawn line"): press on the
   *  scan, drag to where it belongs on the plan, let go. Called once with the ratio of the two distances from the
   *  calibration tie (else the dog), which the page posts as the new scale. */
  stretch?: (factor: number) => void;
  /** Storybook samples only (built into nothing until Johnny picks): extra SVG drawn last, with the map's own projection. */
  overlay?: (P: (p: XY) => XY) => React.ReactNode;
}

/** Something the rest of the page wants lit on the map (a receipts row, a stop in a list). */
export type MapFocus =
  | { kind: "stop"; id: string; label?: string }
  | { kind: "device"; id: string; label?: string }
  | { kind: "point"; position: XY; label: string };

export interface TwinMapProps {
  /** Called on a zoom, a key pan or a reset a person made (Overview disarms "Scale by a wall" on it). */
  onViewChange?: () => void;
  grid?: Grid;
  floorPlan?: FloorPlan;
  zones?: Zone[];
  routes?: Route[];
  stops?: Stop[];
  devices?: Device[];
  looks?: Look[];
  /** A run is active: the dog pin turns highlight. */
  runActive?: boolean;
  focus?: MapFocus | null;
  /** Route id whose draw-on animation should play (the one orchestrated moment). */
  drawRouteId?: string | null;
  /** Edit mode: a click on the map itself (not a pin), in meters. */
  onMapClick?: (xy: XY) => void;
  onStopClick?: (stopId: string) => void;
  selectedStopIds?: string[];
  /** A zone being drawn, in meters. */
  draft?: XY[];
  /** Small, read-only frame: no legend, zoom controls, or heat key. */
  compact?: boolean;
  /** Controls placed on the map, bottom right (e.g. the scout button). */
  actions?: React.ReactNode;
  /** The live layers (Overview). Unset on the fixture pages. */
  live?: LiveLayers;
  /** Layer switches to start with (Storybook's off / on views); the Layers panel still changes them. */
  initialLayers?: Partial<Record<LayerKey, boolean>>;
  className?: string;
}

interface View { s: number; tx: number; ty: number }
/** Fit padding: room for the legend (left), zoom buttons (right), and the heat key (bottom). */
const PAD = { l: 24, r: 56, t: 56, b: 72 };

export function TwinMap({
  grid, floorPlan, zones = [], routes = [], stops = [], devices = [], looks = [],
  runActive, focus, drawRouteId, onMapClick, onStopClick, selectedStopIds = [], draft, compact, actions, live, initialLayers, className, onViewChange,
}: TwinMapProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [view, setView] = useState<View | null>(null);
  const [legendOpen, setLegendOpen] = useState(false);
  const [houseFailed, setHouseFailed] = useState(false);   // house.svg did not load: say so, never draw the broken image
  const [houseLoaded, setHouseLoaded] = useState(false);
  const [hoverZone, setHoverZone] = useState<{ id: string; x: number; y: number } | null>(null);   // the no-go zone under the pointer   // fades in once its bytes are here, not as an empty frame
  // toggle B: the last scans, oldest first (a fading sweep); each keeps the scale it was projected at, so a frame from
  // before a scale change is not drawn after it
  const trail = useRef<Frame[]>([]);
  useEffect(() => {
    // the head's law audit: a scan that stopped (the LiDAR off, the dog gone) takes its sweep with it, never left drawn as live
    trail.current = live?.scan?.length ? [...trail.current.slice(-5), { pts: live.scan, known: live.scanKnown, z: live.scanZ, pxPerM: live.pxPerM }] : [];
  }, [live?.scan, live?.scanKnown, live?.scanZ, live?.pxPerM]);
  // One depth ramp over every served height on the map (the head: "so live and memory read as one depth scale"); null
  // when none is served, and then nothing is coloured by height
  const depth = live ? heightSpan(live.cells?.tops, live.heights?.segments, live.scanZ) : null;
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>(() => ({
    grid: true, floorplan: true, zones: true, route: true, stops: true, lights: true, camera: true, dog: true, pins: true,
    scan: true, house: true, heights: false, memory: true, decisions: true, plan: true,   // plan: Johnny, 19:2x, "just showing the obstacles and ... how the wall would be drawn"   // Johnny, 14:50: memory vs live "which he likes and wants on"; 2.5D stays his switch
    ...initialLayers,
    ...(live && !initialLayers ? savedLayers() : {}),
  }));
  // The live map remembers its layer switches across reloads (Johnny's opening shot keeps the house plan off); Storybook's
  // initialLayers win there. Everything the switches change is drawn only on the client, after the first measure.
  useEffect(() => { if (live && !initialLayers) localStorage.setItem("wtdd.map.layers", JSON.stringify(layers)); }, [layers, live, initialLayers]);
  const relief = reliefOn(live, layers, depth);
  const { resolvedTheme } = useTheme();
  const hatchId = useId().replace(/:/g, "");

  const lights = devices.filter((d) => d.kind === "light");
  const cameras = devices.filter((d) => d.kind === "camera");
  const served = devices.find((d) => d.kind === "body");
  // While the dog is being dragged to calibrate it, it is drawn where the hand puts it; the served pose returns after.
  const [dogDrag, setDogDrag] = useState<{ p: XY; h: number } | null>(null);
  const body = served && dogDrag ? { ...served, position: dogDrag.p, headingDeg: dogDrag.h } : served;
  // The room the dog's served position lies in (a highlight only; no number comes of it). Johnny: "a change in BG whenever
  // a dog is entering a different room".
  const here = body && live?.rooms?.find((r) => inside(body.position, r.poly));
  const lookPins = looks.flatMap((l) => l.pins.map((p) => ({ ...p, stop: l.stop })));

  /* World bounds in meters: the grid's extent and the floor plan's segments. */
  const frame = (live?.fit ?? live?.frame)?.join(",");
  const bounds = useMemo(() => {
    if (frame) { const [minX, minY, maxX, maxY] = frame.split(",").map(Number); return { minX, minY, maxX, maxY }; }
    const xs: number[] = [], ys: number[] = [];
    if (grid) for (const [ix, iy] of grid.cells) { xs.push(ix * grid.cellMeters, (ix + 1) * grid.cellMeters); ys.push(iy * grid.cellMeters, (iy + 1) * grid.cellMeters); }
    if (floorPlan) for (const [x1, y1, x2, y2] of floorPlan.segments) { xs.push(x1, x2); ys.push(y1, y2); }
    for (const d of devices) { xs.push(d.position[0]); ys.push(d.position[1]); }
    if (!xs.length) return { minX: 0, minY: 0, maxX: 10, maxY: 10 };
    return { minX: Math.min(...xs), minY: Math.min(...ys), maxX: Math.max(...xs), maxY: Math.max(...ys) };
  }, [grid, floorPlan, devices, frame]);

  const fit = useCallback((w: number, h: number): View => {
    const bw = bounds.maxX - bounds.minX, bh = bounds.maxY - bounds.minY;
    const pad = compact ? { l: 12, r: 12, t: 12, b: 12 } : w < 640 ? { l: 16, r: 16, t: 56, b: 72 } : PAD;
    const aw = w - pad.l - pad.r, ah = h - pad.t - pad.b;
    const s = Math.max(frame ? 1e-3 : 1, Math.min(aw / bw, ah / bh));
    return { s, tx: pad.l + (aw - bw * s) / 2 - bounds.minX * s, ty: pad.t + (ah - bh * s) / 2 - bounds.minY * s };
  }, [bounds, compact, frame]);

  /* Track the frame size; keep refitting until a person pans or zooms. */
  const moved = useRef(false);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => {
      const { width: w, height: h } = e.contentRect;
      setSize({ w, h });
      setView((v) => (v && moved.current ? v : fit(w, h)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);

  const reset = useCallback(() => { moved.current = false; setView(fit(size.w, size.h)); }, [fit, size]);
  const zoomAt = useCallback((factor: number, cx: number, cy: number) => {
    moved.current = true;
    setView((v) => {
      if (!v) return v;
      const [lo, hi] = frame ? [fit(size.w, size.h).s / 4, fit(size.w, size.h).s * 40] : [8, 400];
      const s = Math.min(hi, Math.max(lo, v.s * factor));
      const k = s / v.s;
      return { s, tx: cx - (cx - v.tx) * k, ty: cy - (cy - v.ty) * k };
    });
  }, [frame, fit, size]);
  const pan = useCallback((dx: number, dy: number) => {
    moved.current = true;
    setView((v) => (v ? { ...v, tx: v.tx + dx, ty: v.ty + dy } : v));
  }, []);

  const viewChanged = useRef(onViewChange);   // the wheel listener is attached once; it reads the newest callback
  useEffect(() => { viewChanged.current = onViewChange; }, [onViewChange]);
  /* Wheel zoom (non-passive so the page doesn't scroll). */
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      viewChanged.current?.();
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  /* Drag to pan. Pins are buttons, so drags start only on the map itself. */
  const drag = useRef<{ x: number; y: number; travel: number } | null>(null);
  // "scale by a wall": the grabbed point and where the hand is, about the tie (else the dog)
  const [grab, setGrab] = useState<{ from: XY; to: XY } | null>(null);
  const pivot = live?.tie ?? served?.position;
  const onPointerDown = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest("button,[data-map-ui]")) return;
    if (live?.stretch && pivot) {
      const at = toWorld(e.clientX, e.clientY);
      setGrab({ from: at, to: at });
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      return;
    }
    drag.current = { x: e.clientX, y: e.clientY, travel: 0 };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (grab) { setGrab({ ...grab, to: toWorld(e.clientX, e.clientY) }); return; }
    if (!drag.current) return;
    const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y;
    const travel = drag.current.travel + Math.abs(dx) + Math.abs(dy);
    if (!onMapClick || travel > 4) pan(dx, dy);
    drag.current = { x: e.clientX, y: e.clientY, travel };
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (grab) {
      setGrab(null);
      const f = stretchOf(grab, pivot);
      if (f && live?.stretch && Math.hypot(grab.to[0] - grab.from[0], grab.to[1] - grab.from[1]) * (view?.s ?? 1) > 4) live.stretch(f);   // a tap posts nothing
      return;
    }
    const d = drag.current;
    drag.current = null;
    if (!d || d.travel > 4 || !onMapClick || !view || !wrapRef.current) return;
    const r = wrapRef.current.getBoundingClientRect();
    onMapClick([(e.clientX - r.left - view.tx) / view.s, (e.clientY - r.top - view.ty) / view.s]);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.target !== e.currentTarget) return;
    onViewChange?.();
    const step = 40;
    const k: Record<string, () => void> = {
      ArrowLeft: () => pan(step, 0), ArrowRight: () => pan(-step, 0), ArrowUp: () => pan(0, step), ArrowDown: () => pan(0, -step),
      "+": () => zoomAt(1.25, size.w / 2, size.h / 2), "=": () => zoomAt(1.25, size.w / 2, size.h / 2),
      "-": () => zoomAt(0.8, size.w / 2, size.h / 2), "0": reset,
    };
    if (k[e.key]) { e.preventDefault(); k[e.key](); }
  };

  /* Occupancy grid on the canvas, colored by served hit count along the heat ramp. */
  useEffect(() => {
    const c = canvasRef.current;
    if (!c || !view) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.round(size.w * dpr);
    c.height = Math.round(size.h * dpr);
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);
    if (live) { drawLive(ctx, getComputedStyle(c), live, view, layers, trail.current, depth); return; }
    if (!grid || !layers.grid) return;
    const css = getComputedStyle(c);
    const color: Record<string, string> = {};
    const cell = grid.cellMeters * view.s;
    const gap = cell > 6 ? 1 : 0;
    const r = cell > 10 ? 2 : 0;
    for (const [ix, iy, count] of grid.cells) {
      if (count < grid.threshold) continue;
      const token = heatToken(count);
      ctx.fillStyle = color[token] ??= css.getPropertyValue(token).trim();
      const x = ix * grid.cellMeters * view.s + view.tx, y = iy * grid.cellMeters * view.s + view.ty;
      if (x + cell < 0 || y + cell < 0 || x > size.w || y > size.h) continue;
      ctx.beginPath();
      ctx.roundRect(x + gap / 2, y + gap / 2, cell - gap, cell - gap, r);
      ctx.fill();
    }
  }, [grid, view, size, layers, resolvedTheme, live, depth]);

  // Johnny, live: the scale slider "keeps the dog and the lidar points the same". The API re-projects the scan around the
  // calibration tie when px_per_m changes, so the view zooms by old/new about the tie (#69's cal.map): the scan holds still
  // on screen and the house plan grows or shrinks around it. Before an API that serves the tie, about the dog, which is
  // exact while it stands where it was last placed. No tie and no dog, no zoom.
  const seenScale = useRef(live?.pxPerM);
  useEffect(() => {
    const was = seenScale.current, now = live?.pxPerM, at = live?.tie ?? served?.position;
    seenScale.current = now;
    if (was && now && at && view && was !== now) zoomAt(was / now, at[0] * view.s + view.tx, at[1] * view.s + view.ty);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a change of the served scale zooms, from the view and dog of that moment
  }, [live?.pxPerM]);

  const P = (p: XY): XY => (view ? [p[0] * view.s + view.tx, p[1] * view.s + view.ty] : [0, 0]);
  const toWorld = useCallback((cx: number, cy: number): XY => {
    const r = wrapRef.current!.getBoundingClientRect();
    return view ? [(cx - r.left - view.tx) / view.s, (cy - r.top - view.ty) / view.s] : [0, 0];
  }, [view]);
  const pts = (poly: XY[]) => poly.map((p) => P(p).join(",")).join(" ");

  const focusPos: { xy: XY; label?: string } | null = useMemo(() => {
    if (!focus) return null;
    if (focus.kind === "point") return { xy: focus.position, label: focus.label };
    if (focus.kind === "stop") { const s = stops.find((x) => x.id === focus.id); return s ? { xy: s.position, label: focus.label ?? s.name } : null; }
    const d = devices.find((x) => x.id === focus.id);
    return d ? { xy: d.position, label: focus.label ?? d.name } : null;
  }, [focus, stops, devices]);

  const legend: Array<{ key: LayerKey; label: string }> = [
    { key: "grid", label: "Grid" }, { key: "floorplan", label: "Floor plan" }, { key: "zones", label: "Zones" },
    { key: "route", label: "Route" }, { key: "stops", label: "Stops" }, { key: "lights", label: "Lights" },
    { key: "camera", label: "Camera" }, { key: "dog", label: "Dog" }, { key: "pins", label: "Pins" },
    ...(live ? [{ key: "plan" as const, label: "Walls and obstacles" }, { key: "scan" as const, label: "Live scan" }, { key: "house" as const, label: "House plan" },
      { key: "heights" as const, label: "2.5D heights" }, { key: "memory" as const, label: "Memory vs live" },
      { key: "decisions" as const, label: "Decisions" }] : []),
  ];

  return (
    <div
      ref={wrapRef}
      tabIndex={0}
      role="application"
      aria-label="Site map. Arrow keys pan, plus and minus zoom, 0 resets the view."
      onKeyDown={onKeyDown}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => { drag.current = null; setGrab(null); }}
      className={cn(
        "relative isolate h-[560px] w-full touch-none select-none overflow-hidden rounded-xl bg-twin-canvas outline-none",
        onMapClick || live?.stretch ? "cursor-crosshair" : "cursor-grab active:cursor-grabbing",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        className,
      )}
    >
      <canvas ref={canvasRef} className="absolute inset-0 size-full" aria-hidden />

      {view && (
        <svg className="pointer-events-none absolute inset-0 size-full" aria-hidden>
          <defs>
            <pattern id={hatchId} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" stroke={MAP_ALERT} strokeWidth="2" />
            </pattern>
          </defs>

          {here && layers.house && (
            <polygon key={`room-${here.name}`} points={pts(here.poly)} fill={MAP_INK} fillOpacity={0.07} className="wtdd-room-enter" />
          )}
          {live?.house && layers.house && !houseFailed && (() => {
            const [a, b] = P([live.frame[0], live.frame[1]]), [c, d] = P([live.frame[2], live.frame[3]]);
            // lighten: the inverted paper background is darker than the canvas, so it drops out and only the lines stay (no panel inside the panel)
            return <image href={live.house} x={a} y={b} width={c - a} height={d - b} style={{ filter: "invert(1)", mixBlendMode: "lighten", opacity: houseLoaded ? 0.55 : 0, transition: "opacity 150ms cubic-bezier(0.22, 1, 0.36, 1)" }}
              onLoad={() => setHouseLoaded(true)} onError={() => setHouseFailed(true)} />;
          })()}


          {layers.floorplan && !planOn(live, layers, depth) && floorPlan?.segments.map(([x1, y1, x2, y2], i) => {
            const [a, b] = P([x1, y1]), [c, d] = P([x2, y2]), top = live?.heights?.segments[i];
            return <line key={i} x1={a} y1={b} x2={c} y2={d} style={{ stroke: top != null && depth ? rampCss(rampT(top, depth)) : MAP_INK }} strokeWidth={2} strokeLinecap="round" />;
          })}

          {layers.zones && zones.map((z) => z.kind === "nogo" ? (
            <polygon key={z.id} points={pts(z.polygon)} fill={`url(#${hatchId})`} fillOpacity={0.55} stroke={MAP_ALERT} strokeWidth={1.5}
              style={{ pointerEvents: "visiblePainted", cursor: "help" }}
              onMouseMove={(e) => { const r = wrapRef.current?.getBoundingClientRect(); if (r) setHoverZone({ id: z.id, x: e.clientX - r.left, y: e.clientY - r.top }); }}
              onMouseLeave={() => setHoverZone(null)} />
          ) : (
            <polygon key={z.id} points={pts(z.polygon)} fill="var(--highlight)" fillOpacity={0.12} stroke="var(--highlight)" strokeWidth={1.5} strokeDasharray="5 4" />
          ))}

          {layers.route && routes.map((r) => {
            const refused = r.status === "refused";
            const draw = drawRouteId === r.id;
            return (
              <polyline
                key={r.id}
                points={pts(r.polyline)}
                fill="none"
                stroke={refused ? MAP_ALERT : live ? MAP_INK_MUTED : MAP_INK}   // live: the drawn path is the dimmest line, under the plan and the walk
                strokeWidth={live ? 1.5 : 2}
                strokeDasharray={refused ? "6 5" : undefined}
                strokeLinejoin="round"
                strokeLinecap="round"
                pathLength={draw ? 1 : undefined}
                className={draw ? "wtdd-route-draw" : undefined}
              />
            );
          })}

          {live && layers.scan && !layers.memory && (live.scan?.length ?? 0) > 0 && (
            <path d={live.scan!.map((p) => { const [x, y] = P(p); return `M${x} ${y}h0`; }).join("")} stroke={MAP_INK} strokeOpacity={0.7} strokeWidth={3} strokeLinecap="round" />
          )}
          {/* The lights as the field drives them (Johnny: "see it turn the lights on or off"): each light glows by its served level,
              and the field's reach is a faint ring around where the dog is believed to be. Nothing drawn when no walk runs. */}
          {live?.field && layers.lights && (() => {
            const [fx, fy] = P(live.field.p), lv = live.field.levels;
            return (
              <g>
                <defs><radialGradient id={`${hatchId}-glow`}><stop offset="0" style={{ stopColor: "var(--heat-peak)", stopOpacity: 0.95 }} /><stop offset="1" style={{ stopColor: "var(--heat-peak)", stopOpacity: 0 }} /></radialGradient></defs>
                <circle cx={fx} cy={fy} r={live.field.radius * (view?.s ?? 1)} fill="none" stroke={MAP_INK} strokeOpacity={0.3} strokeWidth={1} strokeDasharray="4 5" />
                {live.lamps?.map((l) => {
                  const level = lv[l.id];
                  if (!level) return null;   // off, or not served: no glow
                  if (l.kind === "line" && l.pts.length === 2) { const [a, b] = P(l.pts[0]), [c, d] = P(l.pts[1]); return <line key={`glow-${l.id}`} x1={a} y1={b} x2={c} y2={d} style={{ stroke: "var(--heat-peak)" }} strokeOpacity={(level / 100) * 0.7} strokeWidth={16} strokeLinecap="round" />; }
                  const [x, y] = P(l.pts[0]);
                  return <circle key={`glow-${l.id}`} cx={x} cy={y} r={34} fill={`url(#${hatchId}-glow)`} opacity={level / 100} />;
                })}
              </g>
            );
          })()}
          {live && layers.lights && live.lamps?.filter((l) => l.kind === "line" && l.pts.length === 2).map((l) => {
            const [a, b] = P(l.pts[0]), [c, d] = P(l.pts[1]);
            return <line key={l.id} x1={a} y1={b} x2={c} y2={d} stroke={MAP_INK} strokeWidth={4} strokeLinecap="round" />;
          })}
          {/* A path dot that is not a stop is small and quiet (Johnny: "if it's not a main dot, make the dot itself smaller");
              the numbered stops keep their pins. */}
          {live && layers.route && !live.onWaypoint && live.waypoints?.map((w, i) => { const [x, y] = P(w); return <circle key={`wp${i}`} cx={x} cy={y} r={2} fill={MAP_INK} fillOpacity={0.55} />; })}
          {live && layers.route && live.planned?.map((leg, i) => (
            <polyline key={`leg${i}`} points={pts(leg)} fill="none" stroke={MAP_INK} strokeWidth={1.5} strokeDasharray="6 5" strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {live && layers.route && (live.trace?.length ?? 0) > 1 && (
            <>
              <polyline points={pts(live.trace!)} fill="none" stroke={MAP_INK} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
              <TraceArrows pts={live.trace!.map(P)} />
            </>
          )}
          {live && layers.decisions && live.decisions?.map((d) => {
            const [x, y] = P(d.position), ink = d.ok ? MAP_INK : "var(--signal-alert)";
            return (
              <g key={`dec${d.n}`}>
                <circle cx={x} cy={y} r={7.5} fill="var(--twin-canvas)" stroke={ink} strokeWidth={1.25} />
                <text x={x} y={y + 3} textAnchor="middle" fill={ink} fontSize={9} fontFamily="IBM Plex Mono, monospace">{d.n}</text>
              </g>
            );
          })}

          {layers.camera && cameras.map((cam) => cam.headingDeg != null && (
            <Cone key={cam.id} at={P(cam.position)} heading={cam.headingDeg} spread={70} length={110} fill={MAP_INK} opacity={0.2} />
          ))}
          {draft && draft.length > 0 && (
            <>
              <polyline points={pts(draft)} fill={MAP_ALERT} fillOpacity={0.15} stroke={MAP_ALERT} strokeWidth={1.5} strokeDasharray="4 3" />
              {draft.map((p, i) => { const [x, y] = P(p); return <circle key={i} cx={x} cy={y} r={3.5} fill={MAP_ALERT} />; })}
            </>
          )}
          {layers.dog && body?.headingDeg != null && (
            <Cone at={P(body.position)} heading={body.headingDeg} spread={50} length={56} fill={runActive ? "var(--highlight)" : MAP_INK} opacity={0.25} />
          )}
          {live?.overlay && live.overlay(P)}
          {grab && pivot && (() => {
            const [px, py] = P(pivot), [ax, ay] = P(grab.from), [bx, by] = P(grab.to), f = stretchOf(grab, pivot);
            return (
              <g>
                <line x1={px} y1={py} x2={bx} y2={by} stroke={MAP_INK} strokeOpacity={0.5} strokeWidth={1} strokeDasharray="4 4" />
                <line x1={ax} y1={ay} x2={bx} y2={by} stroke={MAP_INK} strokeWidth={1.5} />
                <circle cx={ax} cy={ay} r={4} fill="none" stroke={MAP_INK} strokeWidth={1.5} />
                <circle cx={bx} cy={by} r={4} fill={MAP_INK} />
                {f && live?.pxPerM && <text x={bx + 10} y={by - 10} fill={MAP_INK} fontSize={12} fontFamily="IBM Plex Mono, monospace">{live.pxPerM} → {Math.round(live.pxPerM * f * 2) / 2} px/m</text>}
              </g>
            );
          })()}
          {layers.dog && body?.headingDeg != null && live?.pill && view && (() => {
            const h = (body.headingDeg * Math.PI) / 180, w = live.pill.width * view.s, seg = ((live.pill.length - live.pill.width) / 2) * view.s;
            const [x, y] = P(body.position), head = [x + seg * Math.cos(h), y + seg * Math.sin(h)], tail = [x - seg * Math.cos(h), y - seg * Math.sin(h)];
            const ink = runActive ? "var(--highlight)" : MAP_INK;
            return (
              <g>
                <line x1={tail[0]} y1={tail[1]} x2={head[0]} y2={head[1]} stroke={ink} strokeOpacity={0.55} strokeWidth={w} strokeLinecap="round" />
                <circle cx={head[0]} cy={head[1]} r={w * 0.3} fill={ink} />
              </g>
            );
          })()}
        </svg>
      )}

      {/* Pins and labels: HTML, so they stay crisp and are keyboard reachable. */}
      {view && (
        <div className="pointer-events-none absolute inset-0">
          {/* The dots first, so the numbered stops on top of them stay readable (a stop is a dot too; a tap on it is the same dot). */}
          {live?.onWaypoint && layers.route && live.waypoints?.map((w, i) => {
            const [x, y] = P(w);
            return (
              <button key={`wp${i}`} type="button" aria-label={`Dot ${i + 1}`} onClick={() => live.onWaypoint!(i)}
                className="group pointer-events-auto absolute flex size-3.5 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring"
                style={{ left: x, top: y }}>
                {/* the tap target stays 14 px; what shows is a 6 px dot */}
                <span className="size-1.5 rounded-full bg-[#EDEDE7]/70 group-hover:size-2.5 group-hover:bg-[#EDEDE7]" />
              </button>
            );
          })}

          {layers.stops && stops.map((s) => (
            <MapPin key={s.id} at={P(s.position)} size={20} selected={selectedStopIds.includes(s.id)}
              onClick={onStopClick ? () => onStopClick(s.id) : undefined}
              tip={<><div className="font-medium">{s.name}</div>{s.look && <div className="font-mono text-[12px] opacity-80">look: {s.look}</div>}</>}>
              <span className="font-mono text-[11px] font-medium">{s.index}</span>
            </MapPin>
          ))}

          {layers.lights && lights.map((l) => (
            <MapPin key={l.id} at={P(l.position)} tone={l.on ? "peak" : "surface"} glow={l.on ? (l.brightness ?? 0) / 254 : 0}
              tip={<DeviceTip d={l} />}>
              <Lightbulb className="size-3.5" strokeWidth={1.5} />
            </MapPin>
          ))}

          {layers.camera && cameras.map((c) => (
            <MapPin key={c.id} at={P(c.position)} tip={<DeviceTip d={c} />}>
              <Camera className="size-3.5" strokeWidth={1.5} />
            </MapPin>
          ))}

          {layers.dog && body && (
            <MapPin at={P(body.position)} tone={runActive ? "highlight" : "surface"} tip={<DeviceTip d={body} />}>
              <Dog className="size-3.5" strokeWidth={1.5} />
            </MapPin>
          )}
          {layers.dog && body && live?.calibrate && view && (
            <DogHandles at={P(body.position)} origin={body.position} heading={body.headingDeg ?? 0} dragging={dogDrag}
              toWorld={toWorld} onDrag={setDogDrag}
              onRelease={(pose) => { if (pose) live.calibrate!(pose); setTimeout(() => setDogDrag(null), pose ? 1500 : 0); }} />
          )}

          {layers.pins && lookPins.map((p, i) => (
            <MapPin key={i} at={P(p.position)} size={14} shape="diamond"
              tip={<><div className="font-medium">{p.label}</div><div className="font-mono text-[12px] opacity-80">p {p.p.toFixed(2)} · stop {p.stop}</div></>}>
              {null}
            </MapPin>
          ))}

          {live && layers.lights && live.lamps?.map((l) => l.kind === "dot" ? (
            <MapPin key={l.id} at={P(l.pts[0])} size={20} label={live.field?.levels[l.id] != null ? `${l.label} · ${live.field.levels[l.id]}%` : l.label} tip={<div className="font-medium">{l.label} · placed by hand</div>}>
              <Lightbulb className="size-3" strokeWidth={1.5} />
            </MapPin>
          ) : l.pts.length === 2 && (
            <span key={l.id} className="pointer-events-none absolute whitespace-nowrap font-mono text-[11px] leading-4" style={{ left: P(l.pts[0])[0] + 8, top: P(l.pts[0])[1] - 20, color: MAP_INK }}>{live.field?.levels[l.id] != null ? `${l.label} · ${live.field.levels[l.id]}%` : l.label}</span>
          ))}

          {live && layers.pins && live.jev?.map((j) => (
            <div key={`jev-${j.id}`}>
              <MapPin at={P(j.position)} size={12} shape="diamond"   // the name is in its hover tip (Johnny: nothing piled on the map)
                tip={<><div className="font-medium">Jev · {j.text}</div>{j.error && <div className="font-mono text-[12px] text-signal-alert">{j.error}</div>}</>}>
                {null}
              </MapPin>
              {j.error && (   // a failed call is red on its place, never a guessed name
                <span className="pointer-events-none absolute whitespace-nowrap font-mono text-[11px] leading-4 text-signal-alert" style={{ left: P(j.position)[0] + 10, top: P(j.position)[1] - 8 }}>{j.text}</span>
              )}
            </div>
          ))}

          {live && layers.pins && live.objects?.map((o) => (
            <div key={o.id} className={o.stale ? "opacity-40" : undefined}>
              <MapPin at={P(o.position)} size={14} shape="diamond"   // what it is and its p are in its hover tip, never piled on the map
                tip={<><div className="font-medium">{o.label}</div><div className="font-mono text-[12px] opacity-80">p {o.p.toFixed(2)}{o.stale ? " · stale" : ""}</div>{o.message && <div className="text-[12px] opacity-80">{o.message}</div>}</>}>
                {null}
              </MapPin>
            </div>
          ))}

          {/* A proposal's "Awaiting a tap" stays on the map (a person must act); a no-go zone's words are in its hover card only. */}
          {layers.zones && !compact && zones.filter((z) => z.kind !== "nogo").map((z) => {
            const q = z.polygon.map(P), x = Math.min(...q.map((p) => p[0])), y = Math.min(...q.map((p) => p[1]));
            return (
              <span
                key={z.id}
                style={{ left: x + 4, top: y + 4 }}   // inside the zone's top edge: above it, the label sat on the pins nearby
                className={cn(
                  "absolute whitespace-nowrap rounded-sm px-1.5 text-[11px] font-medium leading-4",
                  z.kind === "nogo" ? "bg-signal-alert-soft text-signal-alert" : "bg-highlight text-on-highlight",
                )}
              >
                {z.kind === "nogo" ? z.name : "Awaiting a tap"}
              </span>
            );
          })}

          {hoverZone && layers.zones && (() => {
            const z = zones.find((q) => q.id === hoverZone.id), info = live?.zoneInfo?.[hoverZone.id];
            if (!z) return null;
            return (
              <div data-map-ui className="pointer-events-none absolute z-10 flex w-64 flex-col gap-2 rounded-md border border-border bg-card p-2.5 text-foreground shadow-[0_8px_24px_rgb(0_0_0/0.4)]"
                style={{ left: Math.min(hoverZone.x + 14, size.w - 270), top: Math.min(hoverZone.y + 14, size.h - 250) }}>
                <span className="text-[13px] font-medium">{info?.what ?? z.name}</span>
                {info?.photo ? <Photo img={info.photo} /> : z.drawnBy === "dog" && <span className="font-mono text-[12px] text-muted-foreground">no photo served for this zone</span>}
              </div>
            );
          })()}

          {focusPos && (() => {
            const [x, y] = P(focusPos.xy);
            return (
              <div key={`${x},${y}`} className="absolute" style={{ left: x, top: y }}>
                <span className="wtdd-focus-ring absolute -left-5 -top-5 size-10 rounded-full border-2 border-dashed" style={{ borderColor: MAP_INK }} />
                {focusPos.label && (
                  <span className="absolute left-6 -top-3 whitespace-nowrap rounded-sm bg-card px-1.5 py-0.5 font-mono text-[11px] text-foreground shadow-[0_8px_24px_rgb(0_0_0/0.4)]">
                    {focusPos.label}
                  </span>
                )}
              </div>
            );
          })()}
        </div>
      )}

      {!compact && <>
      {/* Layer legend, top left. */}
      <div data-map-ui className="absolute left-3 top-3 w-40 rounded-md border border-input bg-card text-foreground">
        <button
          type="button"
          aria-expanded={legendOpen}
          onClick={() => setLegendOpen((o) => !o)}
          className="flex h-8 w-full items-center gap-2 rounded-md px-2.5 text-[13px] font-medium outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Layers className="size-4" strokeWidth={1.5} />
          <span className="flex-1 text-left">Layers</span>
          <ChevronDown className={cn("size-4 text-muted-foreground transition-transform duration-150", legendOpen && "rotate-180")} strokeWidth={1.5} />
        </button>
        {legendOpen && <ul className="wtdd-arrive flex flex-col border-t border-border p-1">
          {legend.map((l) => (
            <li key={l.key}>
              <label className="flex h-7 cursor-pointer items-center gap-2 rounded-sm px-1 text-[13px] hover:bg-accent">
                <Switch
                  checked={layers[l.key]}
                  onCheckedChange={(v) => setLayers((s) => ({ ...s, [l.key]: v }))}
                  className="scale-75 -mx-1"
                  aria-label={`Show ${l.label}`}
                />
                <span className="flex-1">{l.label}</span>
              </label>
            </li>
          ))}
        </ul>}
      </div>

      {/* Zoom controls, top right. */}
      <div data-map-ui className="absolute right-3 top-3 flex flex-col gap-1">
        <MapButton label="Zoom in" onClick={() => { onViewChange?.(); zoomAt(1.25, size.w / 2, size.h / 2); }}><Plus /></MapButton>
        <MapButton label="Zoom out" onClick={() => { onViewChange?.(); zoomAt(0.8, size.w / 2, size.h / 2); }}><Minus /></MapButton>
        <MapButton label="Reset view" onClick={() => { onViewChange?.(); reset(); }}><Maximize /></MapButton>
      </div>

      {/* Bottom bar: heat key and honesty line on the left, map actions on the right. When the actions do not fit beside a
          readable status (Calibrate's slider and switches), they wrap to their own row under it (the worker's live check). */}
      <div className="pointer-events-none absolute inset-x-3 bottom-3 flex flex-wrap items-end justify-between gap-x-3 gap-y-2">
      {live ? (
        <div data-map-ui className="pointer-events-auto flex min-w-64 flex-1 flex-col gap-1 font-mono text-[11px]" style={{ color: MAP_INK_MUTED }}>
          {layers.heights && !relief && <span>2.5D · heights not served{live.cells?.topsWhy ? ` · ${live.cells.topsWhy}` : ""}</span>}
          {planOn(live, layers, depth) && <span className="flex items-center gap-1.5">walls <span className="size-2.5 rounded-sm" style={{ background: MAP_INK, opacity: 0.85 }} /> · obstacles, by their measured height:</span>}
          {layers.plan && !live.classCells && <span>walls and obstacles · no floor plan served yet, so the memory is drawn</span>}
          {layers.memory && (depth
            ? <span className="flex items-center gap-1.5">depth {depth[0].toFixed(2)} m <span className="h-2 w-16 rounded-sm" style={{ background: `linear-gradient(to right, ${LIDAR_TOKENS.map((t) => `var(${t})`).join(", ")})` }} /> {depth[1].toFixed(2)} m</span>
            : <span>depth · heights not served</span>)}
          {layers.memory && (live.scan?.length
            ? <span className="flex items-center gap-1.5">{live.scanKnown
                ? <>live, known <span className="size-1.5 rounded-full" style={{ background: live.scanZ ? rampCss(0.5) : MAP_INK, opacity: 0.5 }} /> live, new <span className="size-2 rounded-full" style={{ background: live.scanZ ? rampCss(0.5) : MAP_INK, boxShadow: `0 0 5px ${live.scanZ ? rampCss(0.5) : MAP_INK}` }} /></>
                : "live · known not served"}{!live.scanZ && " · live heights not served"}</span>
            : <span>memory vs live · no live scan · {live.scanWhy ?? "no frame yet"}</span>)}
          {houseFailed && layers.house && (
            <span style={{ color: MAP_ALERT }}>
              house plan · FAILED to load {live.house} ·{" "}
              <button type="button" className="underline underline-offset-2" onClick={() => setHouseFailed(false)}>retry</button>
            </span>
          )}
          {live.status}
        </div>
      ) : grid && layers.grid ? (
        <div data-map-ui className="pointer-events-auto flex min-w-0 flex-col gap-1 font-mono text-[11px]" style={{ color: MAP_INK_MUTED }}>
          <div className="flex items-center gap-1.5">
            <span>hits</span>
            {[{ from: grid.threshold, token: "--heat-cold" }, ...HEAT_BINS].map((b) => (
              <span key={b.token} className="flex items-center gap-1">
                <span className="size-2.5 rounded-sm" style={{ background: `var(${b.token})` }} />
                <span>{b.from}+</span>
              </span>
            ))}
          </div>
        </div>
      ) : <span />}
      {actions && <div data-map-ui className="pointer-events-auto ml-auto flex max-w-full flex-wrap items-center justify-end gap-2">{actions}</div>}
      </div>
      </>}
    </div>
  );
}

/** The layer switches this browser last chose on the live map, or none. */
function savedLayers(): Partial<Record<LayerKey, boolean>> {
  if (typeof window === "undefined") return {};
  try { return JSON.parse(localStorage.getItem("wtdd.map.layers") ?? "{}"); } catch { return {}; }
}

/** Whether a point lies inside a polygon (the ray test today's remote uses for the room a point is in). */
function inside(p: XY, poly: XY[]) {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}

/**
 * The calibration handles (today's remote's drag): the ring on the dog moves where it is, the tip ahead of it turns where
 * it faces. Only a drag that moved calls onRelease with the new pose; a tap does nothing.
 */
function DogHandles({ at, origin, heading, dragging, toWorld, onDrag, onRelease }: {
  at: XY; origin: XY; heading: number; dragging: { p: XY; h: number } | null;
  toWorld: (cx: number, cy: number) => XY; onDrag: (d: { p: XY; h: number } | null | ((d: { p: XY; h: number } | null) => { p: XY; h: number } | null)) => void;
  onRelease: (pose: { p: XY; heading_deg: number } | null) => void;
}) {
  const grab = useRef<{ kind: "dog" | "cone"; moved: boolean; p: XY; h: number } | null>(null);
  const r = (heading * Math.PI) / 180, [x, y] = at, tip: XY = [x + 56 * Math.cos(r), y + 56 * Math.sin(r)];
  function start(kind: "dog" | "cone", e: React.PointerEvent) {
    e.stopPropagation(); (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    grab.current = { kind, moved: false, p: origin, h: heading };
    onDrag({ p: origin, h: heading });
  }
  const downDog = (e: React.PointerEvent) => start("dog", e);
  const downCone = (e: React.PointerEvent) => start("cone", e);
  const move = (e: React.PointerEvent) => {
    const g = grab.current; if (!g) return;
    g.moved = true;
    const w = toWorld(e.clientX, e.clientY);
    if (g.kind === "dog") g.p = w; else g.h = Math.round((Math.atan2(w[1] - g.p[1], w[0] - g.p[0]) * 1800) / Math.PI) / 10;
    onDrag({ p: g.p, h: g.h });
  };
  const up = () => {
    const g = grab.current; grab.current = null;
    onRelease(g?.moved ? { p: [Math.round(g.p[0]), Math.round(g.p[1])], heading_deg: g.h } : null);
  };
  const handle = "pointer-events-auto absolute -translate-x-1/2 -translate-y-1/2 rounded-full cursor-grab active:cursor-grabbing touch-none";
  return (
    <>
      <div data-map-ui role="slider" aria-label="Drag the dog to where it is" aria-valuenow={0} tabIndex={-1}
        className={`${handle} size-7 ring-2 ring-[var(--highlight)]/70`} style={{ left: x, top: y }}
        onPointerDown={downDog} onPointerMove={move} onPointerUp={up} onPointerCancel={up} />
      <div data-map-ui role="slider" aria-label="Drag to where the dog faces" aria-valuenow={Math.round(heading)} tabIndex={-1}
        className={`${handle} size-3.5 border-2 border-[var(--highlight)] bg-[var(--twin-canvas)]`} style={{ left: tip[0], top: tip[1] }}
        onPointerDown={downCone} onPointerMove={move} onPointerUp={up} onPointerCancel={up} />
      {dragging && <span className="pointer-events-none absolute whitespace-nowrap font-mono text-[11px] text-[var(--highlight)]" style={{ left: x + 18, top: y + 18 }}>release to set · {Math.round(dragging.h)}°</span>}
    </>
  );
}

/** Small, slender chevrons along the actual route, about every 64 screen px, pointing the way the dog went. */
function TraceArrows({ pts }: { pts: XY[] }) {
  const out: Array<{ x: number; y: number; a: number }> = [];
  let run = 32;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], len = Math.hypot(x1 - x0, y1 - y0);
    run += len;
    if (run >= 64 && len > 0) { out.push({ x: (x0 + x1) / 2, y: (y0 + y1) / 2, a: (Math.atan2(y1 - y0, x1 - x0) * 180) / Math.PI }); run = 0; }
  }
  return (
    <g>
      {out.map((c, i) => (
        <path key={i} d="M -3.5 -3.5 L 1.5 0 L -3.5 3.5" transform={`translate(${c.x} ${c.y}) rotate(${c.a})`} fill="none"
          stroke={MAP_INK} strokeWidth={1.25} strokeLinecap="round" strokeLinejoin="round" />
      ))}
    </g>
  );
}


/**
 * The live grid and the floor plan's furniture on the canvas: one square per served cell, centred on its corner pixel.
 * Memory vs live (toggle B): the grid is memory, muted grey; the last scans are a fading sweep, a point already a wall in
 * memory (known, served) in half ink and a new one in full ink, larger, with a soft ink glow: brightness carries "new",
 * so the highlight keeps meaning "a person must act". 2.5D (toggle A): each furniture or wall cell with a
 * served top is a prism up to that top, back to front; a cell with none stays flat. Nothing here computes a height.
 */
/**
 * The dither (Johnny, 14:50: "a slight Bayer dithering ... a variation of X's and plus's patterns and of varying colors and
 * depth and saturation"). A 16 px tile of 4 x 4 cells; a cell carries its glyph where the Bayer matrix is under the density,
 * so the texture is ordered, not noise. Glyph, density and colour are chosen from SERVED values only: the cell's class
 * (low "+", slab "x", tall both) and its measured top (S13's class_top_m) in three display bins, like the heat bins.
 * The shapes are the served cells; nothing here draws a shape of its own.
 */
const BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
const DITHER_CELL = 4;
const patterns = new Map<string, CanvasPattern | null>();
function dither(ctx: CanvasRenderingContext2D, glyph: "+" | "x" | "both", density: number, color: string) {
  const key = `${glyph}|${density}|${color}`;
  if (patterns.has(key)) return patterns.get(key)!;
  const tile = document.createElement("canvas");
  tile.width = tile.height = DITHER_CELL * 4;
  const t = tile.getContext("2d")!;
  t.strokeStyle = color; t.lineWidth = 1;
  BAYER.forEach((row, j) => row.forEach((v, i) => {
    if (v >= density * 16) return;
    const x = i * DITHER_CELL + 0.5, y = j * DITHER_CELL + 0.5, e = DITHER_CELL - 1;
    const g = glyph === "both" ? ((i + j) % 2 ? "x" : "+") : glyph;
    t.beginPath();
    if (g === "+") { t.moveTo(x + e / 2, y); t.lineTo(x + e / 2, y + e); t.moveTo(x, y + e / 2); t.lineTo(x + e, y + e / 2); }
    else { t.moveTo(x, y); t.lineTo(x + e, y + e); t.moveTo(x + e, y); t.lineTo(x, y + e); }
    t.stroke();
  }));
  const p = ctx.createPattern(tile, "repeat");
  patterns.set(key, p);
  return p;
}
/** "Walls and obstacles" draws when its switch is on, a floor plan's cells are served and the 2.5D relief is not drawing;
 *  with no floor plan yet, the memory draws as before, so the map is never empty. */
function planOn(live: LiveLayers | undefined, layers: Record<LayerKey, boolean>, depth: [number, number] | null) {
  return !!(live && layers.plan && live.classCells && !reliefOn(live, layers, depth));
}
/** 2.5D's relief: a served height drawn at this share of its true height, so a 1 m top rises 0.3 m of plan (the head). */
const RELIEF = 0.3;
/** The relief is drawn when the 2.5D switch is on and at least one memory cell has a served top at a served scale. */
function reliefOn(live: LiveLayers | undefined, layers: Record<LayerKey, boolean>, depth: [number, number] | null) {
  return !!(live && layers.heights && layers.grid && live.pxPerM && depth && live.cells?.tops?.some((t) => t != null));
}
/** "Scale by a wall": how much farther from the pivot the hand put the grabbed point; null for a grab on the pivot itself. */
function stretchOf(g: { from: XY; to: XY }, pivot?: XY) {
  if (!pivot) return null;
  const a = Math.hypot(g.from[0] - pivot[0], g.from[1] - pivot[1]), b = Math.hypot(g.to[0] - pivot[0], g.to[1] - pivot[1]);
  return a > 2 ? b / a : null;
}
/** Two #rrggbb colours mixed (display only). */
function mix(a: string, b: string, t: number) {
  const n = (h: string) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16));
  const [x, y] = [n(a), n(b)];
  if (x.some(Number.isNaN) || y.some(Number.isNaN)) return a;
  return `#${x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("")}`;
}
/** The measured top in three display bins; with no served top, the class alone says how deep (low < slab < tall). */
const heightBin = (top: number | null | undefined, cls: string) => (top != null ? (top < 0.5 ? 0 : top < 1.0 ? 1 : 2) : cls === "low" ? 0 : cls === "slab" ? 1 : 2);

type Frame = { pts: XY[]; known?: boolean[]; z?: Array<number | null>; pxPerM?: number };

function drawLive(ctx: CanvasRenderingContext2D, css: CSSStyleDeclaration, live: LiveLayers, view: View, layers: Record<LayerKey, boolean>,
  trail: Frame[], depth: [number, number] | null) {
  // the depth ramp's colour for a served height, in 33 steps (one fill per colour, not per cell)
  const stops = LIDAR_TOKENS.map((t) => css.getPropertyValue(t).trim()), steps = new Map<number, string>();
  const ramp = (v: number) => {
    const q = Math.round(rampT(v, depth!) * 32);
    let c = steps.get(q);
    if (!c) { const u = (q / 32) * (stops.length - 1), i = Math.min(stops.length - 2, Math.floor(u)); c = mix(stops[i], stops[i + 1], u - i); steps.set(q, c); }
    return c;
  };
  const square = (cells: XY[], cell: number, paint: (i: number) => void) => {
    const w = cell * view.s, h = w / 2;
    cells.forEach(([x, y], i) => { paint(i); ctx.fillRect(x * view.s + view.tx - h, y * view.s + view.ty - h, w, w); });
  };
  const plan = planOn(live, layers, depth);
  if (live.cells && layers.grid && !reliefOn(live, layers, depth) && !plan) {
    const { cells, cell, hits } = live.cells, color: Record<string, string> = {};
    const one = css.getPropertyValue(HEAT_FLOOR_TOKEN).trim();
    if (layers.memory) {
      // memory: a "+" dither on the depth ramp by each cell's served top (Johnny: "apply the lidar colorscheme ... the depth
      // to be color calculated"); a cell the floor plan has no top for is one muted ink. With no tops served at all, the heat
      // colour of its served hits, as before.
      const tops = depth ? live.cells.tops : undefined, groups = new Map<string, XY[]>();
      cells.forEach((p, i) => {
        const top = tops?.[i], t = hits ? heatToken(hits[i]) : HEAT_FLOOR_TOKEN;
        const c = tops ? (top != null ? ramp(top) : MAP_INK_MUTED) : (color[t] ??= css.getPropertyValue(t).trim() || one);
        (groups.get(c) ?? groups.set(c, []).get(c)!).push(p);
      });
      ctx.globalAlpha = 0.6;   // Johnny, live: "the memory should be a little less opacity": the live scan and the walls read over it
      for (const [c, group] of groups) { ctx.fillStyle = dither(ctx, "+", 0.55, c) ?? c; square(group, cell, () => {}); }
      ctx.globalAlpha = 1;
    }
    else square(cells, cell, (i) => { const t = hits ? heatToken(hits[i]) : HEAT_FLOOR_TOKEN; ctx.fillStyle = hits ? (color[t] ??= css.getPropertyValue(t).trim()) : one; });
  }
  if (reliefOn(live, layers, depth)) {
    // 2.5D (Johnny's switch; the head's plan): every memory cell raised by its served top (GET /dog/grid top_m, else the
    // floor plan's class_top_m at that cell) as an oblique relief at RELIEF of true height, so a 1 m top does not tower
    // over the room behind it: the top in the depth ramp's colour, the side facing the viewer darker, back to front. A
    // cell with no served top stays flat in muted ink. Memory's "+" and the furniture dither are not drawn under it.
    const { cells, cell } = live.cells!, tops = live.cells!.tops!, w = cell * view.s, half = w / 2, k = live.pxPerM! * view.s * RELIEF;
    const base = css.getPropertyValue("--twin-canvas").trim(), side = new Map<string, string>();
    const order = cells.map((_, i) => i).sort((a, b) => cells[a][1] - cells[b][1]);   // back to front
    for (const i of order) {
      const X = cells[i][0] * view.s + view.tx, Y = cells[i][1] * view.s + view.ty, t = tops[i];
      if (t == null) { ctx.globalAlpha = 0.35; ctx.fillStyle = MAP_INK_MUTED; ctx.fillRect(X - half, Y - half, w, w); ctx.globalAlpha = 1; continue; }
      const c = ramp(t), h = t * k;
      ctx.fillStyle = side.get(c) ?? side.set(c, mix(c, base, 0.45)).get(c)!; ctx.fillRect(X - half, Y + half - h, w, h);   // the side
      ctx.fillStyle = c; ctx.fillRect(X - half, Y - half - h, w, w);                                                         // the top
    }
  } else if (plan) {
    // Johnny, 19:2x: "just showing the obstacles and showing how the wall would be drawn and defined". The floor plan's own
    // cells, solid: its wall cells in ink (the walls as it defined them), every other class (low, slab, tall: the obstacles)
    // on the depth ramp by its served top (muted ink with none). No raw memory, no fitted runs, no dither.
    const { cell, byClass } = live.classCells!, tops = live.heights?.classes ?? {};
    for (const [cls, pts] of Object.entries(byClass)) {
      const groups = new Map<string, XY[]>();
      pts.forEach((p, i) => { const t = tops[cls]?.[i], c = cls === "wall" ? MAP_INK : t != null && depth ? ramp(t) : MAP_INK_MUTED; (groups.get(c) ?? groups.set(c, []).get(c)!).push(p); });
      ctx.globalAlpha = cls === "wall" ? 0.85 : 0.9;
      for (const [c, group] of groups) { ctx.fillStyle = c; square(group, cell, () => {}); }
    }
    ctx.globalAlpha = 1;
  } else if (live.classCells && layers.floorplan) {
    // the furniture, dithered: the canvas colour under it (so the grid's squares do not show through), then the glyphs
    const { cell, byClass } = live.classCells, tops = live.heights?.classes ?? {};
    const base = css.getPropertyValue("--twin-canvas").trim(), deep = css.getPropertyValue(HEAT_FLOOR_TOKEN).trim();
    const glyph: Record<string, "+" | "x" | "both"> = { low: "+", slab: "x", tall: "both" };
    const tone = [mix(MAP_INK_MUTED, deep, 0.15), mix(MAP_INK, deep, 0.45), mix(MAP_INK, deep, 0.7)];   // deeper and more saturated as it gets taller
    const density = [0.4, 0.6, 0.85];
    for (const cls of ["low", "slab", "tall"] as const) {
      // glyph by class, density by height; the colour is the depth ramp's for a served top (muted ink without one), or,
      // with no tops served at all, the class's tone as before
      const groups = new Map<string, { b: number; c: string; pts: XY[] }>();
      (byClass[cls] ?? []).forEach((p, i) => {
        const top = tops[cls]?.[i], b = heightBin(top, cls), c = top != null && depth ? ramp(top) : live.heights ? MAP_INK_MUTED : tone[b];
        const key = `${b}${c}`;
        (groups.get(key) ?? groups.set(key, { b, c, pts: [] }).get(key)!).pts.push(p);
      });
      for (const { b, c, pts: group } of groups.values()) {
        ctx.globalAlpha = 0.85; ctx.fillStyle = base; square(group, cell, () => {});
        ctx.globalAlpha = 1; ctx.fillStyle = dither(ctx, glyph[cls], density[b], c) ?? c; square(group, cell, () => {});
      }
    }
  }
  if (layers.memory && layers.scan && trail.length) {
    // Johnny: "I liked it slightly better when it was painted, but can we apply the lidar colorscheme on it and for the depth
    // to be color calculated". Each point on the depth ramp by its served z_m (one ink until z_m is served). New vs known is
    // size and solidity, never colour (the head): a new point is painted, a soft halo under a solid core; a known one is a
    // small dot at half strength. One path per colour, not a shadow per point.
    const dots = (pts: XY[], c: string, r: number, a: number) => {
      if (!pts.length) return;
      ctx.globalAlpha = a; ctx.fillStyle = c; ctx.beginPath();
      for (const [x, y] of pts) { const X = x * view.s + view.tx, Y = y * view.s + view.ty; ctx.moveTo(X + r, Y); ctx.arc(X, Y, r, 0, Math.PI * 2); }
      ctx.fill();
    };
    trail.forEach((f, k) => {
      if (f.pxPerM !== live.pxPerM) return;   // projected at another scale
      const fade = (k + 1) / trail.length, byColour = new Map<string, { fresh: XY[]; known: XY[] }>();
      f.pts.forEach((p, i) => {
        const z = f.z?.[i], c = z != null && depth ? ramp(z) : MAP_INK;
        const g = byColour.get(c) ?? byColour.set(c, { fresh: [], known: [] }).get(c)!;
        (f.known && f.known[i] !== false ? g.known : g.fresh).push(p);
      });
      for (const [c, g] of byColour) { dots(g.known, c, 1.25, 0.5 * fade); dots(g.fresh, c, 4, 0.2 * fade); dots(g.fresh, c, 2, fade); }
    });
    ctx.globalAlpha = 1;
  }
}

function Cone({ at, heading, spread, length, fill, opacity }: { at: XY; heading: number; spread: number; length: number; fill: string; opacity: number }) {
  const rad = (d: number) => (d * Math.PI) / 180;
  const a = rad(heading - spread / 2), b = rad(heading + spread / 2);
  const [x, y] = at;
  const d = `M${x},${y} L${x + Math.cos(a) * length},${y + Math.sin(a) * length} A${length},${length} 0 0 1 ${x + Math.cos(b) * length},${y + Math.sin(b) * length} Z`;
  return <path d={d} fill={fill} fillOpacity={opacity} />;
}

function MapButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <ActionButton intent="secondary" size="icon" className="size-8 [&_svg]:size-4" aria-label={label} onClick={onClick}>
          {children}
        </ActionButton>
      </TooltipTrigger>
      <TooltipContent side="left" className={MAP_TIP}>{label}</TooltipContent>
    </Tooltip>
  );
}
