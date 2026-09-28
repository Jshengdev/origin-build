"use client";
/**
 * "Walk the route" with the checkpoint look (Johnny, 19:3x: "when it's taking a photo there should be a flow ... where it
 * looks up and down to take a photo, I want that to be a function at a checkpoint"). POST /tools/walk_path {source:
 * "dog", act: true} (wtdd/tools/walk_path.py): the follower drives the dog along the saved route, the lights follow it,
 * and at every stop the dog does the map's action there (actions[i]: its look, and a post to the group only when `say`).
 *   Nothing posts unless a stop says so: walk_path's own default for a stop with no action is a tilt look AND a post, so
 *   before walking, ONE POST /map (with _version) gives every stop without an explicit `say` the entry {look: "tilt",
 *   say: false}, keeping any key it has. The result line says how many. If that save fails, nothing walks.
 *   No stops on the map: a straight walk, POST /dog/follow, as before (no look).
 *   The walk answers only when it ends, so it is fired with hours of timeout and never holds the page; progress is GET
 *   /field (the stop it is at) and /dog/state's follow. Its answer is the result line: served numbers and each stop's
 *   action, a failed one FAILED with its error, and a stop whose post a Stop skipped (walk_path's `stopped`) named and
 *   not counted as posted. A refusal (a walk already running, not calibrated, a no-go zone) is FAILED.
 *   With the Lights switch's own field on, a walk is refused on the page: FAILED "Turn Lights off first", with a button
 *   that turns it off (POST /field/stop). The page never posts /field/stop on its own: a stale stop could end the walk.
 */
import { useState } from "react";
import { ActionButton, LiveMark, SignalChip } from "@/components/wtdd";
import { post, type DogState, type FieldJson, type MapJson } from "@/lib/data/api";
import type { Result } from "@/components/live/stop";

type Action = { stop?: number; look?: string; say?: boolean; ok?: boolean; error?: string; stopped?: string | null };
const LIGHTS = "Turn Lights off first: the walk drives the lights itself";

/** The walk's answer as one line: its served numbers and each stop's action, a failed one as FAILED. */
export function walkLine(what: string, r: { ok: boolean; error?: string; result?: unknown }): Result {
  if (!r.ok) return { what, ok: false, error: r.error };
  const out = (r.result ?? {}) as { seconds?: number; writes?: number; actions?: Action[] };
  const acts = out.actions ?? [], failed = acts.filter((a) => a.ok === false), posted = acts.filter((a) => a.ok !== false && a.say && !a.stopped).length;
  const parts = [
    out.seconds != null && `${out.seconds} s`,
    out.writes != null && `${out.writes} light writes`,
    acts.length > 0 && `${acts.length - failed.length} of ${acts.length} stops looked, ${posted} posted`,
    ...failed.map((a) => `stop at dot ${(a.stop ?? -1) + 1} FAILED: ${a.error ?? "no error served"}`),
    ...acts.filter((a) => a.stopped).map((a) => `stop at dot ${(a.stop ?? -1) + 1}: ${a.stopped}`),
  ].filter(Boolean);
  const line = `${what}${parts.length ? ` · ${parts.join(" · ")}` : ""}`;
  return failed.length ? { what: line, ok: false } : { what: line, ok: true };
}

/** The route's stops with no explicit `say` get {look: "tilt", say: false}, other keys kept; null when none needs it. */
export function lookWithoutPosting(m: MapJson): { actions: NonNullable<MapJson["actions"]>; n: number } | null {
  const actions = { ...(m.actions ?? {}) };
  let n = 0;
  for (const i of m.stops ?? []) {
    const a = actions[String(i)] ?? {};
    if (a.say === undefined) { actions[String(i)] = { look: "tilt", ...a, say: false }; n++; }
  }
  return n ? { actions, n } : null;
}

export function useWalkRoute(field: FieldJson | undefined, onResult: (r: Result) => void, onSaved?: (m: MapJson) => void) {
  const [starting, setStarting] = useState(false);
  const [lightsBlocked, setLightsBlocked] = useState(false);
  const lightsOn = !!field?.p && field.follower === false;   // the Lights switch's own field
  /** `map`: the served map to walk (Routines: the one its load answered with, through `before`). */
  const start = async (what: string, map: MapJson | null | undefined, before?: () => Promise<{ ok: boolean; error?: string; map?: MapJson }>) => {
    if (lightsOn) { setLightsBlocked(true); onResult({ what, ok: false, error: LIGHTS }); return; }
    setLightsBlocked(false);
    setStarting(true);
    let m = map ?? null;
    if (before) {
      const b = await before();
      if (!b.ok) { setStarting(false); onResult({ what, ok: false, error: b.error }); return; }
      m = b.map ?? m;
    }
    if (!m) { setStarting(false); onResult({ what, ok: false, error: "the map has not loaded" }); return; }
    if (!(m.stops ?? []).length) {   // no stops: a straight walk, as before
      const r = await post("/dog/follow", {});
      setStarting(false);
      onResult(r.ok ? { what: `${what} · no stops, so no look`, ok: true } : { what, ok: false, error: r.error });
      return;
    }
    const prep = lookWithoutPosting(m);
    if (prep) {
      const s = await post("/map", { ...m, actions: prep.actions });
      if (!s.ok) { setStarting(false); onResult({ what: `${what} · not walked: the stops could not be set to look without posting`, ok: false, error: s.error }); return; }
      onSaved?.({ ...m, actions: prep.actions, _version: s._version as number | undefined });
    }
    const running = post("/tools/walk_path", { source: "dog", act: true }, 6 * 3600 * 1000);   // open until the walk ends
    setTimeout(() => setStarting(false), 2000);   // then the buttons follow GET /field and the follow state
    const r = await running;
    setStarting(false);
    onResult(walkLine(prep ? `${what} · ${prep.n} ${prep.n === 1 ? "stop" : "stops"} set to look without posting` : what, r));
  };
  const lightsOff = lightsBlocked && lightsOn ? (
    <ActionButton intent="secondary" size="sm" onClick={async () => { const r = await post("/field/stop", {}); if (!r.ok) onResult({ what: "Turn Lights off", ok: false, error: r.error }); }}>Turn Lights off</ActionButton>
  ) : null;
  return { start, starting, lightsOff };
}

/** "Walking", with the stop it is at while it looks (GET /field's stop among the map's stops), else the follow's waypoint. */
export function WalkProgress({ field, follow, stops }: { field?: FieldJson; follow: DogState["follow"]; stops: number[] }) {
  if (field?.p && field.follower !== false && field.stop != null) {
    const k = stops.indexOf(field.stop);
    return <SignalChip tone="good" mark={<LiveMark />}>Walking · stop {k >= 0 ? `${k + 1} of ${stops.length}` : `at dot ${field.stop + 1}`} · looking and photographing</SignalChip>;
  }
  if (follow?.active) return <SignalChip tone="good" mark={<LiveMark />}>Walking · waypoint {follow.i} of {follow.n}</SignalChip>;
  if (field?.p && field.follower !== false) return <SignalChip tone="good" mark={<LiveMark />}>Walking</SignalChip>;
  return null;
}
