/**
 * The TwinMap views and samples Johnny asked to judge (2026-09-27 04:53: "make these views toggleable so that i can see and
 * judge for myself ... everything else i would need a sample side by side comparison example"). Each story is OFF (v2's
 * map as it is) beside ON, on the same FIXTURE frame (stories/fixtures/live-frame.json: the dry API's shipped map,
 * synthetic furnished room and objects fixture, plus a synthetic scan, follow legs and decision rows; not a night).
 *   Views (built, a switch in Layers): 2.5D heights, memory vs live.
 *   Samples (built into nothing until Johnny picks): walls drawn on in confirmation order, decision markers linked to
 *   their receipt rows, planned vs trace styling, a replay scrubber. Their drawing lives here, in the story, only.
 * Open with `pnpm storybook` (http://localhost:6310), "Map/Views and samples".
 */
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { useEffect, useState } from "react";
import { TwinMap, type LayerKey, type MapFocus, type TwinMapProps } from "@/components/twin/twin-map";
import { MAP_INK } from "@/components/twin/heat";
import { shapeLive } from "@/components/twin/use-live-map";
import type { DogState, FloorPlanPx, GridPx, LidarPx, MapJson, ObjectsPx, XY } from "@/lib/data/api";
import frameJson from "./fixtures/live-frame.json";

type Frame = {
  map: MapJson; grid: GridPx; floorplan: FloorPlanPx; objects: ObjectsPx; scale: { px_per_m: number }; lidar: LidarPx;
  dog: { p: XY; heading_deg: number }; follow: { planned: XY[][]; trace: XY[] };
  decisions: Array<{ ts: string; tool: string; ok: boolean; at: XY; say: string }>;
};
const F = frameJson as unknown as Frame;
const dog = { connected: true, calibrated: true, recheck: false, avoid: true, moving: false, vel: [0, 0, 0], state: { age_ms: 120 },
  map: F.dog, follow: { ...F.follow, active: true, i: 3, n: F.map.path.length } } as unknown as DogState;
const base = shapeLive({ map: F.map, grid: F.grid, plan: F.floorplan, objects: F.objects, lidar: F.lidar, pxPerM: F.scale.px_per_m,
  dog, fresh: true, house: "/stories/house.svg" });
const FIT: [number, number, number, number] = [180, 250, 720, 760];   // the fixture's furnished room and the route through it

function Map({ layers, overlay, focus, extra }: { layers?: Partial<Record<LayerKey, boolean>>; overlay?: (P: (p: XY) => XY) => React.ReactNode; focus?: MapFocus | null; extra?: Partial<TwinMapProps> }) {
  return <TwinMap {...base} live={base.live && { ...base.live, overlay, fit: FIT }} initialLayers={layers} focus={focus} className="h-[620px]" {...extra} />;
}

function SideBySide({ name, off, on, note }: { name: string; off: React.ReactNode; on: React.ReactNode; note: string }) {
  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-[15px] font-semibold">{name}</h2>
        <p className="text-[13px] text-muted-foreground">{note}</p>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-2"><span className="font-mono text-[12px] text-muted-foreground">off · v2 as it is</span>{off}</div>
        <div className="flex flex-col gap-2"><span className="font-mono text-[12px] text-muted-foreground">on · {name}</span>{on}</div>
      </div>
    </div>
  );
}

const meta: Meta = { title: "Map/Views and samples", parameters: { layout: "fullscreen" } };
export default meta;
type Story = StoryObj;

export const Heights: Story = {
  name: "View A · 2.5D heights",
  render: () => <SideBySide name="2.5D heights" note="Walls and furniture raised to their measured tops (GET /dog/floorplan segments_top_m, class_top_m). A run or cell with no top stays flat."
    off={<Map />} on={<Map layers={{ heights: true }} />} />,
};

export const Memory: Story = {
  name: "View B · memory vs live",
  render: () => <SideBySide name="Memory vs live" note="One depth ramp, low blue to high lime: memory (GET /dog/grid) and the floor plan by their served tops, the live scan (GET /dog/lidar) by its served z_m. A live point not yet a wall in memory (known false) is painted, a soft halo under a solid core; a known one is a small dot at half strength."
    off={<Map layers={{ memory: false }} />} on={<Map layers={{ memory: true }} />} />,
};

/** Sample 1: the floor plan's wall runs drawn on one after another, ink by how many cells each run holds (served n). */
function DrawOn() {
  const segs = F.floorplan.segments_px;
  const ink = (n: number) => (n >= 150 ? 1 : n >= 80 ? 0.7 : 0.45);
  return (
    <Map layers={{ floorplan: false }} overlay={(P) => (
      <g>
        <style>{"@keyframes wtdd-draw { from { stroke-dashoffset: 1 } to { stroke-dashoffset: 0 } }"}</style>
        {segs.map(([x0, y0, x1, y1, n], i) => {
          const [a, b] = P([x0, y0]), [c, d] = P([x1, y1]);
          return (
            <g key={i}>
              <line x1={a} y1={b} x2={c} y2={d} stroke={MAP_INK} strokeOpacity={ink(n)} strokeWidth={3} strokeLinecap="round" pathLength={1}
                strokeDasharray="1" style={{ animation: `wtdd-draw 700ms ease-out ${i * 700}ms both` }} />
              <text x={(a + c) / 2 + 6} y={(b + d) / 2 - 6} fill={MAP_INK} fontSize={11} fontFamily="IBM Plex Mono, monospace">run {i + 1} · {n} cells</text>
            </g>
          );
        })}
      </g>
    )} />
  );
}
export const WallsDrawOn: Story = {
  name: "Sample 1 · walls drawn on in confirmation order",
  render: () => <SideBySide name="Walls drawn on, confidence ink" note="Each wall run draws on in the order the floor plan served it; its ink is set by the cells it holds (served n), so a thin run reads lighter."
    off={<Map />} on={<DrawOn />} />,
};

/** Sample 2: a numbered marker where each decision was made; a receipt row lights its marker. */
function Decisions() {
  const [focus, setFocus] = useState<MapFocus | null>(null);
  return (
    <div className="flex flex-col gap-2">
      <Map focus={focus} overlay={(P) => F.decisions.map((r, i) => {
        const [x, y] = P(r.at);
        return <g key={i}><circle cx={x} cy={y} r={9} fill="var(--card)" stroke={MAP_INK} strokeWidth={1.5} /><text x={x} y={y + 4} textAnchor="middle" fill={MAP_INK} fontSize={10} fontFamily="IBM Plex Mono, monospace">{i + 1}</text></g>;
      })} />
      <ol className="flex flex-col rounded-md border border-border">
        {F.decisions.map((r, i) => (
          <li key={i} onMouseEnter={() => setFocus({ kind: "point", position: r.at, label: `route.decided · ${i + 1}` })} onMouseLeave={() => setFocus(null)}
            className="grid cursor-default grid-cols-[28px_1fr] gap-2 border-t border-border px-3 py-2 text-[13px] first:border-t-0 hover:bg-accent">
            <span className="font-mono text-[12px] text-muted-foreground">{i + 1}</span><span>{r.say}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
export const DecisionMarkers: Story = {
  name: "Sample 2 · decision markers linked to receipts",
  render: () => <SideBySide name="Decision markers ↔ receipts" note="Each route.decided row gets a numbered marker where it was made; hovering its receipt lights the marker."
    off={<Map />} on={<Decisions />} />,
};

/** Sample 3: the plan's legs numbered where they start, the actual route with arrows for its direction. */
function PlanTrace() {
  return (
    <Map overlay={(P) => (
      <g>
        <defs><marker id="wtdd-arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--highlight)" /></marker></defs>
        {F.follow.planned.map((leg, i) => { const [x, y] = P(leg[0]); return <text key={i} x={x - 30} y={y - 8} fill={MAP_INK} fontSize={11} fontFamily="IBM Plex Mono, monospace">leg {i + 1}</text>; })}
        {F.follow.trace.slice(1).map((p, i) => {
          const [a, b] = P(F.follow.trace[i]), [c, d] = P(p);
          return <line key={i} x1={a} y1={b} x2={c} y2={d} stroke="var(--highlight)" strokeWidth={2.5} markerEnd="url(#wtdd-arrow)" />;
        })}
      </g>
    )} />
  );
}
export const PlannedVsTrace: Story = {
  name: "Sample 3 · planned vs trace styling",
  render: () => <SideBySide name="Planned vs trace" note="The planned legs named where each starts; the actual route carries arrows, so which way it went reads at a glance."
    off={<Map />} on={<PlanTrace />} />,
};

/** Sample 4: scrub a run's decision rows; the map lights where each happened and says what the dog said. */
function Replay() {
  const [k, setK] = useState(0);
  const [play, setPlay] = useState(false);
  useEffect(() => {
    if (!play) return;
    const t = setInterval(() => setK((n) => (n + 1) % F.decisions.length), 1200);
    return () => clearInterval(t);
  }, [play]);
  const r = F.decisions[k];
  return (
    <div className="flex flex-col gap-2">
      <Map focus={{ kind: "point", position: r.at, label: `${r.ts.slice(11)} · ${r.tool}` }} />
      <div className="flex items-center gap-3">
        <button type="button" className="rounded-md border border-input bg-card px-3 py-1 text-[13px]" onClick={() => setPlay((p) => !p)}>{play ? "Pause" : "Play"}</button>
        <input type="range" min={0} max={F.decisions.length - 1} value={k} onChange={(e) => setK(+e.target.value)} className="flex-1" aria-label="Replay" />
        <span className="font-mono text-[12px] text-muted-foreground">{k + 1} of {F.decisions.length}</span>
      </div>
      <p className="text-[13px]">{r.say}</p>
    </div>
  );
}
export const ReplayScrubber: Story = {
  name: "Sample 4 · replay scrubber for a run's record",
  render: () => <SideBySide name="Replay scrubber" note="Scrub (or play) a run's decision rows: the map lights where each happened and shows what the dog said."
    off={<Map />} on={<Replay />} />,
};
