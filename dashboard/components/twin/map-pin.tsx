"use client";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { Device } from "@/lib/data";
import { MAP_INK } from "./heat";

type XY = [number, number];

/** A tooltip over the map: surface, a line edge and the one shadow a floating layer may use. Stock ink-on-ink is 1.01:1 on the canvas. */
export const MAP_TIP = "border border-border bg-card text-foreground shadow-[0_8px_24px_rgb(0_0_0/0.4)] [&_svg]:bg-card [&_svg]:fill-card";

/**
 * DevicePin / map pin: a button at a screen position on the TwinMap. 24px circle with a 1.5px icon by default.
 * Tones: surface (idle), peak (a lamp that is on), highlight (the dog during an active run).
 * `glow` is the lamp's served brightness scaled to 0..1; nothing pulses on its own.
 */
export function MapPin({ at, children, tip, tone = "surface", size = 24, label, glow = 0, shape = "circle", selected, onClick }: {
  at: XY; children: React.ReactNode; tip: React.ReactNode; tone?: "surface" | "peak" | "highlight"; size?: number;
  label?: string; glow?: number; shape?: "circle" | "diamond"; selected?: boolean; onClick?: () => void;
}) {
  const tones = {
    surface: "bg-card text-foreground border-input",
    peak: "bg-heat-peak text-on-highlight border-transparent",
    highlight: "bg-highlight text-on-highlight border-transparent",
  };
  return (
    <div className="pointer-events-auto absolute" style={{ left: at[0], top: at[1] }}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={onClick}
            aria-pressed={onClick ? !!selected : undefined}
            className={cn(
              "absolute flex items-center justify-center border outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-twin-canvas",
              shape === "circle" ? "rounded-full" : "rotate-45 rounded-sm bg-card border-foreground/40",
              tones[tone],
              selected && "ring-2 ring-[#EDEDE7] ring-offset-2 ring-offset-twin-canvas",
            )}
            style={{
              width: size, height: size, left: -size / 2, top: -size / 2,
              boxShadow: glow ? `0 0 ${8 + glow * 16}px ${glow * 6}px color-mix(in srgb, var(--heat-peak) ${Math.round(glow * 60)}%, transparent)` : undefined,
            }}
          >
            {children}
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className={MAP_TIP}>{tip}</TooltipContent>
      </Tooltip>
      {label && (
        <span className="pointer-events-none absolute whitespace-nowrap font-mono text-[11px] leading-4" style={{ left: size / 2 + 4, top: -8, color: MAP_INK }}>
          {label}
        </span>
      )}
    </div>
  );
}

export function DeviceTip({ d }: { d: Device }) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="font-medium">{d.name}</div>
      <div className="font-mono text-[12px] opacity-80">
        {d.status}
        {d.vitals && ` · battery ${d.vitals.batteryPct}%`}
        {d.kind === "light" && ` · ${d.on ? `on ${d.brightness}` : "off"}`}
      </div>
      {d.placedBy && <div className="text-[12px] opacity-80">{d.placedBy === "hand" ? "Placed by hand" : "Placed by a click, not measured"}</div>}
    </div>
  );
}
