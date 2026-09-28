"use client";
/**
 * One photo a run's row names (GET /images, #73), as the API says it is. Only a photo whose file is this row's own is
 * drawn: a `replaced` one (a newer look wrote the same name after the row) is a labelled tile with no bytes, because the
 * picture at its url is a later look's; a `missing` one says the file is not in the pictures folder; a picture that does
 * not load says FAILED. The bytes come through the app's proxy (/api/pictures/<file>). Real photos from inside the house:
 * shown live only, never screenshotted or committed.
 * `share` (the albums: Routines' looks, the Images page; Johnny, 19:4x: "put it in the routines photos album and I can
 * choose to send it to the group chat with a button in it, and people can respond, and it'll save the responses for me"):
 * "Send to group" arms on the first press and posts on the second within 4 s (POST /images/share {file, caption, by}); once
 * sent, the photo says "sent HH:MM · N replies" and lists the replies, both as GET /images serves them. A 409 means a
 * question is open in the chat; any other refusal is FAILED with its reason. A replaced or missing photo cannot be sent.
 */
import { useEffect, useState } from "react";
import { ActionButton } from "@/components/wtdd";
import { post, redact, type RunImage } from "@/lib/data/api";
import { clock } from "@/lib/format";

export function Photo({ img, label, share }: { img: RunImage; label?: string; share?: boolean }) {
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
      {share && !img.replaced && !img.missing && <Share img={img} />}
    </figure>
  );
}

function Share({ img }: { img: RunImage }) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [line, setLine] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { if (!armed) return; const t = setTimeout(() => setArmed(false), 4000); return () => clearTimeout(t); }, [armed]);
  const by = () => (typeof window === "undefined" ? "" : localStorage.getItem("wtdd.scout.by") ?? "").trim() || "Johnny";
  const send = async () => {
    setArmed(false); setBusy(true);
    const r = await post("/images/share", { file: img.file, ...(img.caption ? { caption: img.caption } : {}), by: by() });
    setBusy(false);
    setLine(r.ok ? { ok: true, text: "posted to the group · replies show here as they come" }
      : { ok: false, text: / 409:/.test(r.error ?? "") ? "a question is open in the chat; answer it or Reset chat first" : `FAILED ${redact(r.error ?? "no answer")}` });
  };
  const replies = img.replies ?? [];
  return (
    <div className="flex flex-col gap-1.5 border-t border-border pt-1.5">
      {img.shared && <span className="font-mono text-[12px] text-muted-foreground">sent {clock(img.shared.at)} · {replies.length} {replies.length === 1 ? "reply" : "replies"}</span>}
      {replies.length > 0 && (
        <ul className="flex flex-col gap-1">
          {replies.map((x, i) => <li key={`${x.ts}-${i}`} className="text-[13px]"><span className="font-medium">{redact(x.by)}</span> <span className="font-mono text-[11px] text-muted-foreground">{clock(x.ts)}</span><br />{redact(x.text)}</li>)}
        </ul>
      )}
      <span className="flex flex-wrap items-center gap-2">
        <ActionButton intent={armed ? "person" : "secondary"} size="sm" disabled={busy} title="POST /images/share: post this photo to THE CASTLE; the group's replies are saved under it"
          onClick={() => (armed ? send() : setArmed(true))}>{armed ? `Confirm · post as ${by()}` : img.shared ? "Send again" : "Send to group"}</ActionButton>
        {armed && <span className="text-[12px] text-muted-foreground">Post this photo to THE CASTLE?</span>}
      </span>
      {line && <span className={`font-mono text-[12px] ${line.ok ? "text-muted-foreground" : "text-signal-alert"}`}>{line.text}</span>}
    </div>
  );
}
