"use client";
/**
 * One photo a run's row names (GET /images, #73), as the API says it is. Only a photo whose file is this row's own is
 * drawn: a `replaced` one (a newer look wrote the same name after the row) is a labelled tile with no bytes, because the
 * picture at its url is a later look's; a `missing` one says the file is not in the pictures folder; a picture that does
 * not load says FAILED. The bytes come through the app's proxy (/api/pictures/<file>). Real photos from inside the house:
 * shown live only, never screenshotted or committed.
 */
import { useState } from "react";
import { redact, type RunImage } from "@/lib/data/api";
import { clock } from "@/lib/format";

export function Photo({ img, label }: { img: RunImage; label?: string }) {
  const [failed, setFailed] = useState(false);
  const note = img.replaced ? `replaced · a newer look wrote ${img.file} after this row, so its photo is gone`
    : img.missing ? `missing · ${img.file} is not in the pictures folder`
    : failed ? `FAILED to load ${img.file}` : null;
  return (
    <figure className="flex flex-col gap-1.5">
      {note ? (
        <div className={`flex aspect-video w-full items-center justify-center rounded-md border border-dashed p-3 text-center font-mono text-[12px] ${img.replaced ? "border-border text-muted-foreground" : "border-signal-alert text-signal-alert"}`}>{note}</div>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={`/api${img.url}`} alt={img.caption ? redact(img.caption) : `the dog's ${img.kind} photo`} onError={() => setFailed(true)}
          className="aspect-video w-full rounded-md object-cover" />
      )}
      <figcaption className="flex flex-col gap-0.5">
        <span className="font-mono text-[12px] text-muted-foreground">{[label, clock(img.ts), !img.ok && "its row FAILED"].filter(Boolean).join(" · ")}</span>
        {img.caption && <span className="text-[13px]">{redact(img.caption)}</span>}
      </figcaption>
    </figure>
  );
}
