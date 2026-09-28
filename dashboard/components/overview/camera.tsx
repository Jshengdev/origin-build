"use client";
/**
 * The dog's camera on Overview (Johnny, 17:00: "add in the live video stream so we can see the site map and also the
 * camera ... at a glance"). GET /api/dog/frame.jpg is the newest front-camera JPEG; the API refuses a stale one with a
 * 503 and its reason. Self-paced like today's remote: the next frame is asked for only after the last one arrived (about
 * 3 a second), cache-busted, and none while the tab is hidden. It asks ONLY while GET /dog/state says the dog is connected, so opening the page never
 * connects the dog. A failed frame is a red FAILED with the API's reason and the picture is taken down, never the last
 * good frame left up as if live; it retries every 2 s. The caption is when this page received the frame shown.
 * Real frames from inside the house: shown live only, never screenshotted or committed.
 */
import { useEffect, useState } from "react";
import { Module } from "@/components/wtdd";
import { clock } from "@/lib/format";
import { redact } from "@/lib/data/api";

type Frame = { url: string; at: string } | null;

export function Camera({ connected, className }: { connected: boolean; className?: string }) {
  const [frame, setFrame] = useState<Frame>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!connected) return;
    let alive = true, timer: ReturnType<typeof setTimeout>;
    const swap = (next: Frame) => setFrame((prev) => { if (prev) URL.revokeObjectURL(prev.url); return next; });
    const tick = async () => {
      if (document.hidden) { timer = setTimeout(tick, 1000); return; }   // no frames for a tab nobody is looking at
      try {
        const res = await fetch(`/api/dog/frame.jpg?t=${Date.now()}`, { cache: "no-store" });
        if (!res.ok) {
          const body = await res.json().catch(() => null) as { error?: string } | null;
          throw new Error(`GET /dog/frame.jpg ${res.status}: ${body?.error ?? res.statusText}`);
        }
        const url = URL.createObjectURL(await res.blob());
        if (!alive) { URL.revokeObjectURL(url); return; }
        swap({ url, at: new Date().toISOString() });
        setError(null);
        timer = setTimeout(tick, 333);   // about 3 a second: enough to watch, light on the browser
      } catch (e) {
        if (!alive) return;
        swap(null);   // never the last good frame passed off as live
        setError(e instanceof Error ? e.message : String(e));
        timer = setTimeout(tick, 2000);
      }
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [connected]);

  const shown = connected ? frame : null;
  return (
    <Module title="Camera" size="auto" className={className}
      meta={shown ? `received ${clock(shown.at, "America/Los_Angeles")}` : undefined}
      error={connected && error ? `FAILED ${redact(error)}` : undefined}>
      {shown ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={shown.url} alt="The dog's front camera, live" className="aspect-video w-full rounded-md object-cover" />
      ) : (
        <p className="text-[15px] text-muted-foreground">{connected ? "Waiting for the first frame." : "The dog is not connected. Its camera shows here when it is."}</p>
      )}
    </Module>
  );
}
