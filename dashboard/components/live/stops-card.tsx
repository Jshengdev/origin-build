"use client";
/**
 * The route's stops and what the dog does at each (Johnny, 19:4x: "ensure the routine builder and path have all these
 * functionalities"): one card, on Paths and on Routines, editing map.json's actions for the route on the map. Per stop:
 * "Look up & down" (actions[i].look tilt, else level), "Post to the group" (say) and "Ask here" (the intruder check, ask).
 * A stop with no action looks up and down and does NOT post (the walk saves that before it starts, walk-route.tsx).
 * Each switch saves at once through POST /map with the served map's _version (the 409 guard), keeps the stop's other
 * keys, shows the served state; a refused save is the page's FAILED line. `locked` holds them (an unsaved edit on Paths).
 */
import { useState } from "react";
import { ActionButton, Module } from "@/components/wtdd";
import { post, type MapJson } from "@/lib/data/api";
import type { Result } from "@/components/live/stop";

/** A stop's look in today's remote's words (ui/index.html's stop label). */
const LOOK: Record<string, string> = { tilt: "nod", level: "level", sit: "look up" };
type Actions = NonNullable<MapJson["actions"]>;

export function StopsCard({ served, locked, error, loading, empty, onResult, onSaved, footer }: {
  served?: MapJson | null; locked?: string; error?: string; loading?: boolean; empty: string;
  onResult: (r: Result) => void; onSaved: (m: MapJson) => void; footer?: React.ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const save = async (what: string, actions: Actions) => {
    if (!served) return;
    setBusy(true);
    const r = await post("/map", { ...served, actions });
    setBusy(false);
    onResult(r.ok ? { what, ok: true } : { what, ok: false, error: r.error });
    if (r.ok) onSaved({ ...served, actions, _version: r._version as number | undefined });
  };
  const setAction = (i: number, what: string, patch: { look?: string; say?: boolean }) => {
    const k = String(i), actions = { ...(served?.actions ?? {}) };
    actions[k] = { look: "tilt", ...(actions[k] ?? {}), ...patch };
    return save(what, actions);
  };
  const askHere = (i: number, n: number, on: boolean) => {
    const k = String(i), actions = { ...(served?.actions ?? {}) }, a = { ...(actions[k] ?? {}) };
    if (on) actions[k] = { look: "tilt", ...a, ask: true };
    else { delete a.ask; if (Object.keys(a).length) actions[k] = a; else delete actions[k]; }
    return save(on ? `Ask here · stop ${n}` : `No ask · stop ${n}`, actions);
  };
  const stops = served?.stops ?? [];
  return (
    <Module title="Stops" size="auto" error={error} loading={loading}>
      {stops.length === 0 ? (
        <p className="text-[15px] text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex flex-col">
          {stops.map((i, n) => {
            const entry = served?.actions?.[String(i)], a = entry ?? {};
            const look = (a.look ?? "tilt") === "tilt", say = a.say === true;   // no action saved: looks up and down, no post (the walk saves that first)
            return (
              <li key={i} className="flex flex-wrap items-center gap-2 border-t border-border py-2 first:border-t-0 first:pt-0">
                <span className="text-[13px] font-medium">Stop {n + 1}</span>
                <span className="font-mono text-[12px] text-muted-foreground">dot {i + 1} · {entry ? `${LOOK[a.look ?? "tilt"] ?? a.look}${say ? " + post" : ", no post"}` : "default: look up & down, no post"}</span>
                <span className="ml-auto flex items-center gap-1.5">
                  <ActionButton intent={look ? "primary" : "secondary"} size="sm" aria-pressed={look} disabled={busy || !!locked}
                    title={locked ?? (look ? "At this stop the dog looks down at the floor, then up at the room, and photographs. Tap for one level look instead." : "At this stop the dog takes one level look. Tap to look up and down.")}
                    onClick={() => setAction(i, look ? `Level look · stop ${n + 1}` : `Look up & down · stop ${n + 1}`, { look: look ? "level" : "tilt" })}>Look up & down</ActionButton>
                  <ActionButton intent={say ? "primary" : "secondary"} size="sm" aria-pressed={say} disabled={busy || !!locked}
                    title={locked ?? (say ? "The photo and a sentence go to the group chat. Tap to keep it on the page only." : "The photo stays on the page (Images). Tap to also post it to the group chat.")}
                    onClick={() => setAction(i, say ? `No post · stop ${n + 1}` : `Post to the group · stop ${n + 1}`, { say: !say })}>Post to the group</ActionButton>
                  <ActionButton intent={a.ask ? "primary" : "secondary"} size="sm" aria-pressed={!!a.ask} disabled={busy || !!locked}
                    title={locked ?? (a.ask ? "If the dog sees a person here it asks the on-call person \"who dis?!\" and waits. Tap to stop asking here." : "The intruder check: if the dog sees a person here, it asks who it is and waits for the answer")}
                    onClick={() => askHere(i, n + 1, !a.ask)}>{a.ask ? "Asks here" : "Ask here"}</ActionButton>
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {footer}
    </Module>
  );
}
