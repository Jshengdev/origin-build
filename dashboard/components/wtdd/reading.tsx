import { cn } from "@/lib/utils";

/** A value a machine produced: mono, tabular, with its unit muted. Render only values the API served. */
export function Reading({ value, unit, size = "md", className }: { value: string | number; unit?: string; size?: "sm" | "md"; className?: string }) {
  return (
    <span className={cn("font-mono", className)}>
      <span className={size === "md" ? "text-[20px] leading-6 font-medium" : "text-[13px]"}>{value}</span>
      {unit && <span className="ml-1 text-[12px] text-muted-foreground">{unit}</span>}
    </span>
  );
}
