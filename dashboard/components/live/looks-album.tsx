"use client";
/**
 * "This run's looks" (Johnny, 19:4x: parity between Paths and Routines): the run's look photos at their stops, GET
 * /images?kind=look (#73), each with "Send to group" and the group's replies under it (#96's share on the Photo tile).
 * One album, on Paths and on Routines. An empty run says the served why; a failed read is FAILED.
 */
import { Module } from "@/components/wtdd";
import { redact, usePoll, type ImagesJson } from "@/lib/data/api";
import { Photo } from "@/components/live/photo";

export function LooksAlbum() {
  const looks = usePoll<ImagesJson>("/images?kind=look", 5000);
  return (
    <Module title="This run's looks" meta={looks.data ? `run ${looks.data.shift} · ${looks.data.n}` : undefined} size="auto"
      loading={!looks.data && !looks.error} error={looks.error ? `FAILED GET /images · ${redact(looks.error)}` : undefined}>
      {looks.data && (looks.data.images.length ? (
        <div className="flex flex-col gap-3">
          {looks.data.why && <span className="font-mono text-[12px] text-muted-foreground">{redact(looks.data.why)}</span>}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
            {looks.data.images.map((i, k) => <Photo key={`${i.ts}-${i.file}-${k}`} img={i} label={i.stop != null ? `stop at dot ${i.stop + 1}` : "no stop"} share />)}
          </div>
        </div>
      ) : <p className="text-[13px] text-muted-foreground">{redact(looks.data.why ?? "No look photo in this run yet.")}</p>)}
    </Module>
  );
}
