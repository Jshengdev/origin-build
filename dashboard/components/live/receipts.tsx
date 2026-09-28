"use client";
import { useState } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Module, SignalChip } from "@/components/wtdd";
import { TwinMap } from "@/components/twin/twin-map";
import { clock } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { LedgerRow, MapData } from "@/lib/data";
import { rowDetail, rowFocus, type ReceiptRow } from "./ledger";

// A run of repeats (groupRepeats) is keyed by its oldest row, so a repeat joining it updates the line in place, no new fade
const rowKey = (r: ReceiptRow) => { const o = r.group?.at(-1) ?? r; return `${o.ts}-${o.tool}`; };
/** A run's time: first–last, oldest first. */
const span = (r: ReceiptRow, timeZone: string) => r.group ? `${clock(r.group.at(-1)!.ts, timeZone)}–${clock(r.ts, timeZone)}` : clock(r.ts, timeZone);

export function Result({ ok }: { ok: boolean }) {
  return ok ? <SignalChip tone="neutral">ok</SignalChip> : <SignalChip tone="alert">FAILED</SignalChip>;
}

/** The ledger tail with the item 26 timeline. A row or tick opens the drawer with its place on the map. */
export function Receipts({ rows, map, timeZone, title = "Receipts", meta, error, stub, timeline = true, loading, marker, onPoint }: {
  rows: ReceiptRow[]; map?: MapData; timeZone: string; title?: string; meta?: string; error?: string; stub?: boolean;
  /** A decision row's number on the map (Overview's decision markers). */
  marker?: (r: LedgerRow) => number | undefined;
  /** Hover, focus or arrow keys on a row: light its place on the map (null: nothing lit). A replay of the walk, row by row. */
  onPoint?: (r: LedgerRow | null) => void;
  /** The first read is in flight: three skeleton rows, never "No rows yet". */
  loading?: boolean;
  /** The item 26 timeline; off where 26 is not merged (the live Overview). */
  timeline?: boolean;
}) {
  const [open, setOpen] = useState<ReceiptRow | null>(null);
  const selected = open ? rowKey(open) : null;
  const [pick, setPick] = useState<string | null>(null);   // the open row's own key, same-second counter included

  return (
    <Module title={title} size="full" meta={meta} error={error} stub={stub}>
      {loading ? <RowsSkeleton /> : rows.length === 0 ? (
        <p className="py-6 text-[15px] text-muted-foreground">No rows yet. Rows appear here as the dog walks, looks, and texts.</p>
      ) : (
        <div className="flex flex-col gap-4">
          {timeline && <Timeline rows={rows} selected={selected} onSelect={(r) => { setOpen(r); setPick(null); }} timeZone={timeZone} />}
          <Table>
            <TableHeader>
              <TableRow className="wtdd-arrive hover:bg-transparent">
                <TableHead className="w-24 text-[13px] text-muted-foreground">Time</TableHead>
                <TableHead className="w-36 text-[13px] text-muted-foreground">Tool</TableHead>
                <TableHead className="w-24 text-[13px] text-muted-foreground">Result</TableHead>
                <TableHead className="w-24 text-right text-[13px] text-muted-foreground">Latency</TableHead>
                <TableHead className="text-[13px] text-muted-foreground">Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r, i) => {
                const k = rowKey(r);
                // Rows in the same second with the same tool (four lights.signal) are told apart counting from the oldest,
                // so a new row on top never renames an old one and only the new row plays its fade.
                const u = `${k}-${rows.slice(i + 1).filter((x) => rowKey(x) === k).length}`;
                const pickRow = () => { setOpen(r); setPick(u); };
                return (
                  <TableRow
                    key={u}
                    data-state={(pick ? pick === u : selected === k) ? "selected" : undefined}   // one row lit, not every row in the same second
                    tabIndex={0}
                    onClick={pickRow}
                    onMouseEnter={() => onPoint?.(r)} onMouseLeave={() => onPoint?.(null)} onFocus={() => onPoint?.(r)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pickRow(); }
                      if (e.key === "ArrowDown" || e.key === "ArrowUp") {   // step through the walk, row by row
                        e.preventDefault();
                        const next = (e.key === "ArrowDown" ? e.currentTarget.nextElementSibling : e.currentTarget.previousElementSibling) as HTMLElement | null;
                        next?.focus();
                      }
                    }}
                    className="wtdd-arrive h-10 cursor-pointer outline-none focus-visible:bg-accent data-[state=selected]:bg-accent"
                  >
                    <TableCell className="whitespace-nowrap font-mono text-[12px] text-muted-foreground">
                      {marker?.(r) != null && (
                        <span className={`mr-1.5 inline-flex size-4 items-center justify-center rounded-full border text-[9px] ${r.ok ? "border-foreground/60 text-foreground" : "border-signal-alert text-signal-alert"}`}>{marker(r)}</span>
                      )}
                      {span(r, timeZone)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-mono text-[13px]">{r.tool}{r.group && <span className="ml-1.5 text-muted-foreground">×{r.group.length}</span>}</TableCell>
                    <TableCell><Result ok={r.ok} /></TableCell>
                    <TableCell className="text-right font-mono text-[13px]">{r.latency_ms}<span className="ml-1 text-[12px] text-muted-foreground">ms</span></TableCell>
                    <TableCell className="max-w-0 truncate text-[13px]" title={rowDetail(r)}>{rowDetail(r)}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
      <RowDrawer row={open} map={map} onClose={() => { setOpen(null); setPick(null); }} timeZone={timeZone} />
    </Module>
  );
}

/** The table's own shape while loading: 40px rows on hairlines, a bar in `line` each. Static. */
function RowsSkeleton() {
  return (
    <div aria-label="Loading" className="flex flex-col">
      {["w-2/5", "w-4/5", "w-3/5"].map((w) => (
        <div key={w} className="flex h-10 items-center border-b border-border"><Skeleton className={cn("h-3 animate-none rounded-sm bg-border", w)} /></div>
      ))}
    </div>
  );
}

/** Item 26: a tick per ledger row at its served time, red for ok=false. */
function Timeline({ rows, selected, onSelect, timeZone }: {
  rows: LedgerRow[]; selected: string | null; onSelect: (row: LedgerRow) => void; timeZone: string;
}) {
  const times = rows.map((r) => Date.parse(r.ts));
  const t0 = Math.min(...times), t1 = Math.max(...times);
  const span = Math.max(1, t1 - t0);
  return (
    <div className="relative h-8 rounded-sm border border-border bg-background">
      <div className="absolute inset-y-0 left-2 right-2" role="listbox" aria-label="Receipts timeline">
        {rows.map((r, i) => {
          const k = rowKey(r);
          return (
            <Tooltip key={k}>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  role="option"
                  aria-selected={selected === k}
                  aria-label={`${clock(r.ts, timeZone)} ${r.tool} ${r.ok ? "ok" : "failed"}`}
                  onClick={() => onSelect(r)}
                  style={{ left: `${((times[i] - t0) / span) * 100}%` }}
                  className="group absolute top-0 flex h-full w-3 -translate-x-1/2 items-center justify-center outline-none"
                >
                  <span
                    className={cn(
                      "h-4 w-0.5 rounded-full transition-[height,width] duration-150",
                      r.ok ? "bg-foreground/60" : "bg-signal-alert",
                      "group-hover:h-6 group-focus-visible:h-6",
                      selected === k && "h-6 w-1",
                      selected === k && r.ok && "bg-foreground",
                    )}
                  />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top"><span className="font-mono text-[12px]">{clock(r.ts, timeZone)} · {r.tool}</span></TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </div>
  );
}

function RowDrawer({ row, map, onClose, timeZone }: { row: ReceiptRow | null; map?: MapData; onClose: () => void; timeZone: string }) {
  const taught = map?.routes.find((r) => r.id === "taught");
  const focus = row ? rowFocus(row, taught) : null;
  return (
    <Sheet open={!!row} onOpenChange={(o) => !o && onClose()}>
      {/* Surface, as the DS's drawer; the close button's ring only for the keyboard (a mouse open focuses it too). */}
      <SheetContent side="right"
        className="w-[440px] gap-0 rounded-l-xl bg-card sm:max-w-[440px] data-[state=open]:duration-200 data-[state=closed]:duration-150 [&>button]:focus:ring-0 [&>button]:focus-visible:ring-2">
        {row && (
          <>
            <SheetHeader className="gap-2 border-b border-border p-4">
              <div className="flex items-center gap-2">
                <SheetTitle className="font-mono text-[15px] font-medium">{row.tool}{row.group && <span className="ml-1.5 text-muted-foreground">×{row.group.length}</span>}</SheetTitle>
                <Result ok={row.ok} />
              </div>
              <SheetDescription className="font-mono text-[12px]">
                {span(row, timeZone)}{row.group ? "" : ` · ${row.latency_ms} ms`}{row.stop ? ` · stop ${row.stop}` : ""}{row.cached || row.source === "stub" ? " · stand-in" : ""}
              </SheetDescription>
            </SheetHeader>
            <div className="flex flex-col gap-4 overflow-y-auto p-4">
              {map && focus && (
                <TwinMap
                  {...map}
                  routes={taught ? [taught] : []}
                  looks={[]}
                  focus={focus}
                  compact
                  className="h-[260px]"
                />
              )}
              {row.group ? row.group.map((g, i) => (   // every row of the run, newest first: nothing hidden by the grouping
                <details key={i} open={i === 0} className="flex flex-col gap-2 border-t border-border pt-2 first:border-t-0 first:pt-0">
                  <summary className="cursor-pointer font-mono text-[12px] text-muted-foreground">{clock(g.ts, timeZone)} · {g.latency_ms} ms</summary>
                  <div className="mt-2 flex flex-col gap-4"><RowFields row={g} /></div>
                </details>
              )) : <RowFields row={row} />}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

function RowFields({ row }: { row: LedgerRow }) {
  return (
    <>
      {row.error && <Field label="error"><p className="font-mono text-[13px] text-signal-alert">{row.error}</p></Field>}
      {(["args", "state_before", "state_after"] as const).map((f) => row[f] && (
        <Field key={f} label={f}>
          <pre className="overflow-x-auto rounded-md border border-border bg-background p-2 font-mono text-[12px] leading-4">
            {JSON.stringify(row[f], null, 2)}
          </pre>
        </Field>
      ))}
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1">
      <h3 className="font-mono text-[12px] text-muted-foreground">{label}</h3>
      {children}
    </section>
  );
}
