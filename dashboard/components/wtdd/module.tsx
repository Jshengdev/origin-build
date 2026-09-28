import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";   // stock shadcn
import { Skeleton } from "@/components/ui/skeleton";                               // stock shadcn
import { cn } from "@/lib/utils";
import { StubBadge, StageChip } from "./chips";
import type { Stage } from "./stage";

/**
 * Dashboard module = stock shadcn Card with the DS spacing: 16px padding, 14px radius (rounded-xl). No stroke, no shadow:
 * separation is surface on paper.
 * Sizes are grid spans on a 12-column grid: s=3, m=4, l=6, xl=8, full=12. `auto` sets no span (for modules inside a nested grid).
 * Every module needs empty, loading, and error states: pass `loading`, or `error` with what happened and what to do.
 * Empty is the caller's copy, since it should invite the next action.
 */
const span = { s: "col-span-12 md:col-span-3", m: "col-span-12 md:col-span-4", l: "col-span-12 md:col-span-6", xl: "col-span-12 md:col-span-8", full: "col-span-12", auto: "" } as const;

export function Module({ title, meta, actions, size = "m", stub, stage, loading, error, className, children }: {
  title: string; meta?: string; actions?: ReactNode; size?: keyof typeof span; stub?: boolean; stage?: Stage;
  loading?: boolean; error?: string; className?: string; children?: ReactNode;
}) {
  return (
    <Card className={cn("gap-4 border-0 py-4 shadow-none", span[size], className)} aria-busy={loading || undefined}>
      <CardHeader className="flex flex-row flex-wrap items-center gap-2 px-4">
        <CardTitle className="shrink-0 text-[13px] font-medium">{title}</CardTitle>
        {stage && <StageChip stage={stage} />}
        {stub && <StubBadge />}
        {meta && <span className="ml-auto shrink-0 whitespace-nowrap font-mono text-[12px] text-muted-foreground">{meta}</span>}
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </CardHeader>
      {/* Keyed by state, so content that replaces the skeleton mounts fresh and arrives (150ms fade) instead of popping in. */}
      <CardContent key={loading ? "loading" : error ? "error" : "content"} className={cn("px-4", !loading && !error && "wtdd-arrive")}>
        {loading ? <ModuleSkeleton /> : error ? <ModuleError message={error} /> : children}
      </CardContent>
    </Card>
  );
}

/** Skeleton bars in `line`. Static: no invented motion. */
function ModuleSkeleton() {
  return (
    <div className="flex flex-col gap-2" aria-label="Loading">
      {["w-2/5", "w-4/5", "w-3/5"].map((w) => <Skeleton key={w} className={cn("h-3 animate-none rounded-sm bg-border", w)} />)}
    </div>
  );
}

function ModuleError({ message }: { message: string }) {
  return (
    <p role="alert" className="flex items-baseline gap-2 text-[15px] leading-[22px]">
      <span aria-hidden className="text-signal-alert">●</span>
      <span>{message}</span>
    </p>
  );
}
