/**
 * A page that is not wired to the wtdd API yet (Johnny, 17:15: "keep routines and settings because we need to come back
 * to them"). The page says so at the top, and everything under it is greyed and marked sample, so no status word, count
 * or value on it can pass for live. These pages stay off camera until they read the API.
 */
import { SignalChip } from "@/components/wtdd";

export function SampleFrame({ what, children }: { what: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-4">
      <div role="note" className="flex items-center gap-3 rounded-md border border-border bg-card px-4 py-3">
        <SignalChip tone="neutral">Sample · not live yet</SignalChip>
        <span className="text-[13px] text-muted-foreground">{what} Nothing on this page reads the dog or the ledger.</span>
      </div>
      <div className="pointer-events-none select-none opacity-50 grayscale" aria-disabled>
        {children}
      </div>
    </div>
  );
}
