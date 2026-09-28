"use client";
/**
 * Images on the live API (Johnny, 18:55: "is images not wired in? that should be wired"; the head's spec): the photos a
 * run's rows name (GET /images?shift=<id>, #73), never a folder listing and never a mock.
 *   /images           a run picker from GET /sessions (the run in force, else the newest); the run's photos by stop, a stop
 *                     in time order and "not at a stop" last; each a Photo tile with its kind.
 *   /images/<stop>    "Compare runs": the same stop in each run, newest first, capped at the newest 7 with the cap said.
 * A photo whose file is not its row's own is never drawn (Photo: replaced and missing are labelled tiles); a row that
 * failed has a red edge; an empty run says the served why; a failed read is FAILED with the API's reason.
 */
import Link from "next/link";
import { useState } from "react";
import { Select, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";   // stock shadcn
import { Module, SelectMenu, SignalChip } from "@/components/wtdd";
import { PageActions } from "@/components/shell/page-header";
import { Photo } from "@/components/live/photo";
import { redact, usePoll, type ImagesJson, type RunImage, type Sessions } from "@/lib/data/api";

const CAP = 7;   // runs compared at one stop: the newest 7, and the page says so

/** One photo: the Photo tile, its kind, "replaced" said as a chip too, and a red edge when its row failed (the tile's
 *  caption says "its row FAILED"). */
function ImageCard({ img }: { img: RunImage }) {
  return (
    <div className={`flex flex-col gap-1.5 rounded-md ${img.ok ? "" : "ring-2 ring-signal-alert ring-offset-2 ring-offset-card"}`}>
      <span className="flex flex-wrap items-center gap-1.5">
        <SignalChip tone="neutral">{img.kind}</SignalChip>
        {img.replaced && <SignalChip tone="neutral">replaced: a newer look wrote this name</SignalChip>}
      </span>
      <Photo img={img} />
    </div>
  );
}

/** The run in force, else the newest (GET /sessions is newest first). */
const defaultRun = (s?: Sessions) => s?.find((x) => x.in_force)?.shift_id ?? s?.[0]?.shift_id ?? null;

export function ImagesLive() {
  const sessions = usePoll<Sessions>("/sessions", 10000);
  const [picked, setPicked] = useState<string | null>(null);
  const shift = picked ?? defaultRun(sessions.data);
  const imgs = usePoll<ImagesJson>(shift ? `/images?shift=${encodeURIComponent(shift)}` : null, 5000);
  const list = imgs.data?.images ?? [];
  const stops = [...new Set(list.map((i) => i.stop))].sort((a, b) => (a == null ? 1 : b == null ? -1 : a - b));   // "not at a stop" last
  return (
    <div className="flex flex-col gap-4">
      <PageActions>
        <Select value={shift ?? ""} onValueChange={setPicked} disabled={!sessions.data?.length}>
          <SelectTrigger aria-label="Run" className="h-9 w-[220px] border-input bg-card text-[13px] shadow-none"><SelectValue placeholder={sessions.error ? "runs · FAILED" : sessions.data ? "No runs yet" : "reading runs"} /></SelectTrigger>
          <SelectMenu>
            {(sessions.data ?? []).map((s) => <SelectItem key={s.shift_id} value={s.shift_id} className="text-[13px]">{s.shift_id}{s.in_force ? " · in force" : ""}</SelectItem>)}
          </SelectMenu>
        </Select>
        {sessions.error && <SignalChip tone="alert">Runs · FAILED {redact(sessions.error)}</SignalChip>}
      </PageActions>
      <Module title={shift ? `Photos · ${shift}` : "Photos"} meta={imgs.data ? `${imgs.data.n} ${imgs.data.n === 1 ? "photo" : "photos"}` : undefined} size="auto"
        loading={(!shift && !sessions.data && !sessions.error) || (!!shift && !imgs.data && !imgs.error)}
        error={imgs.error ? `FAILED GET /images · ${redact(imgs.error)}` : !shift && sessions.error ? `FAILED GET /sessions · ${redact(sessions.error)}` : undefined}>
        {!shift ? <p className="text-[13px] text-muted-foreground">No run has a stamped row yet.</p>
          : imgs.data && (list.length === 0 ? <p className="text-[13px] text-muted-foreground">{redact(imgs.data.why ?? "No photo in this run.")}</p> : (
          <div className="flex flex-col gap-6">
            {imgs.data.why && <span className="font-mono text-[12px] text-muted-foreground">{redact(imgs.data.why)}</span>}
            {stops.map((st) => (
              <section key={String(st)} className="flex flex-col gap-3">
                <h3 className="flex items-center gap-3 text-[14px] font-medium">
                  {st == null ? "Not at a stop" : `Stop at dot ${st + 1}`}
                  {st != null && <Link href={`/images/${st}`} className="text-[13px] font-normal text-muted-foreground underline underline-offset-2">Compare runs</Link>}
                </h3>
                <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
                  {list.filter((i) => i.stop === st).map((i, k) => <ImageCard key={`${i.ts}-${i.file}-${k}`} img={i} />)}
                </div>
              </section>
            ))}
          </div>
        ))}
      </Module>
    </div>
  );
}

/** One run's photos at one stop, or "no photo at this stop"; its own read, so one failed run never hides the others. */
function RunAtStop({ shift, stop, inForce }: { shift: string; stop: number; inForce: boolean }) {
  const imgs = usePoll<ImagesJson>(`/images?shift=${encodeURIComponent(shift)}`, 10000);
  const here = (imgs.data?.images ?? []).filter((i) => i.stop === stop);
  return (
    <li className="flex flex-col gap-3 border-t border-border py-4 first:border-t-0 first:pt-0">
      <span className="flex items-center gap-2 font-mono text-[13px]">{shift}{inForce && <SignalChip tone="neutral">in force</SignalChip>}</span>
      {imgs.error ? <p className="font-mono text-[12px] text-signal-alert">FAILED GET /images · {redact(imgs.error)}</p>
        : !imgs.data ? <p className="text-[13px] text-muted-foreground">reading</p>
        : here.length === 0 ? <p className="text-[13px] text-muted-foreground">no photo at this stop</p>
        : <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">{here.map((i, k) => <ImageCard key={`${i.ts}-${i.file}-${k}`} img={i} />)}</div>}
    </li>
  );
}

export function CompareStop({ stop }: { stop: number }) {
  const sessions = usePoll<Sessions>("/sessions", 10000);
  const runs = (sessions.data ?? []).slice(0, CAP);   // newest first, as served
  return (
    <div className="flex flex-col gap-4">
      <PageActions>
        <Link href="/images" className="text-[13px] text-muted-foreground underline underline-offset-2">All photos</Link>
      </PageActions>
      <Module title={`Compare runs · stop at dot ${stop + 1}`} size="auto"
        meta={sessions.data ? `${runs.length} of ${sessions.data.length} ${sessions.data.length === 1 ? "run" : "runs"}${sessions.data.length > CAP ? `, the newest ${CAP}` : ""}` : undefined}
        loading={!sessions.data && !sessions.error} error={sessions.error ? `FAILED GET /sessions · ${redact(sessions.error)}` : undefined}>
        {sessions.data && (runs.length === 0 ? <p className="text-[13px] text-muted-foreground">No run has a stamped row yet.</p> : (
          <ul className="flex flex-col">{runs.map((r) => <RunAtStop key={r.shift_id} shift={r.shift_id} stop={stop} inForce={r.in_force} />)}</ul>
        ))}
      </Module>
    </div>
  );
}
