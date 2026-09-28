import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";            // stock shadcn, never edited
import { cn } from "@/lib/utils";
import { type Stage, stageLabel } from "./stage";

const chip = "rounded-md font-sans text-[12px] leading-4 font-medium px-2 py-0.5 shadow-none";

/** On every element fed by fixtures. */
export function StubBadge({ className }: { className?: string }) {
  return <Badge variant="outline" className={cn(chip, "rounded-sm border-heat-peak text-foreground text-[11px]", className)}>stub</Badge>;
}

/** EXISTS on main · BUILT · PR #n · BUILDING · NOT BUILT */
export function StageChip({ stage, className }: { stage: Stage; className?: string }) {
  return <Badge variant="outline" className={cn(chip, "bg-background border-border text-muted-foreground text-[11px]", className)}>{stageLabel(stage)}</Badge>;
}

/** Status never relies on color alone: good carries ↗, alert carries ●. */
/** A live state: a small square, everywhere live is shown. */
export function LiveMark({ className }: { className?: string }) {
  return <span aria-hidden className={cn("inline-block size-2 shrink-0 rounded-[1px] bg-current", className)} />;
}

/** `mark` overrides the default marker (for example <LiveMark /> for a live state). */
export function SignalChip({ tone, mark: markOverride, children, className }: { tone: "good" | "alert" | "neutral"; mark?: ReactNode; children: ReactNode; className?: string }) {
  const tones = {
    good: "bg-signal-good-soft text-signal-good border-transparent",
    alert: "bg-signal-alert-soft text-signal-alert border-transparent",
    neutral: "bg-background text-muted-foreground border-border",
  } as const;
  const mark = markOverride ?? (tone === "good" ? "↗ " : tone === "alert" ? "● " : "");
  return <Badge variant="outline" className={cn(chip, tones[tone], className)}>{mark}{children}</Badge>;
}

/** "Waiting on a person": an open ask, a proposed zone, an unsigned record. */
export function WaitingChip({ children, className }: { children: ReactNode; className?: string }) {
  return <Badge className={cn(chip, "bg-highlight text-on-highlight border-transparent", className)}>{children}</Badge>;
}
