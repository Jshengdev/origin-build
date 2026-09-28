import { cn } from "@/lib/utils";
import { Reading } from "./reading";

/**
 * Sparkline of served values: 1.5px ink line, the last point as a 4px dot, and an optional threshold band
 * in signal-alert-soft. It draws the points it is given; it computes no averages, rates, or trends.
 */
export function Sparkline({ values, band, width = 160, height = 32, className, label }: {
  values: number[]; band?: [number, number]; width?: number; height?: number; className?: string; label?: string;
}) {
  if (values.length === 0) return <span className="font-mono text-[12px] text-muted-foreground">no values served</span>;
  const lo = Math.min(...values, ...(band ?? [])), hi = Math.max(...values, ...(band ?? []));
  const pad = 3;
  const x = (i: number) => (values.length === 1 ? width / 2 : pad + (i / (values.length - 1)) * (width - pad * 2));
  const y = (v: number) => (hi === lo ? height / 2 : height - pad - ((v - lo) / (hi - lo)) * (height - pad * 2));
  const last = values.length - 1;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={cn("overflow-visible", className)} role="img" aria-label={label}>
      {band && <rect x={0} width={width} y={y(band[1])} height={Math.max(0, y(band[0]) - y(band[1]))} fill="var(--signal-alert-soft)" />}
      <polyline points={values.map((v, i) => `${x(i)},${y(v)}`).join(" ")} fill="none" stroke="var(--foreground)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(last)} cy={y(values[last])} r={2} fill="var(--foreground)" />
    </svg>
  );
}

/** Gauge tile: a label, the served value in `reading` style with its unit, and an optional sparkline. */
export function Gauge({ label, value, unit, history, band, className }: {
  label: string; value: string | number; unit?: string; history?: number[]; band?: [number, number]; className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <span className="text-[13px] font-medium text-muted-foreground">{label}</span>
      <Reading value={value} unit={unit} />
      {history && <Sparkline values={history} band={band} label={`${label} history`} />}
    </div>
  );
}
