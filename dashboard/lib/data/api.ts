"use client";
/**
 * The adapter to the wtdd API (origin-build's wtdd/api.py), read through the /api/* proxy in next.config.ts.
 *
 * The shapes below are the API's own, read from wtdd/api.py and the ledger on origin-build main (the repo wins over the
 * view models in types.ts). Every position is a map pixel in the house frame, as served: nothing here converts units.
 *
 * Fail loud: a route that fails, or answers with an `error`, gives `error` = the route and the reason, and no data. The
 * page shows it as a red FAILED; it never falls back to a fixture.
 */
import { useEffect, useState } from "react";

export type XY = [number, number];

/** GET /dog/state. */
export interface DogState {
  connected: boolean; moving: boolean; vel: number[]; calibrated: boolean; recheck: boolean; avoid: boolean | null;
  state: { age_ms?: number; mode?: number | string; position?: number[] } | null;
  map: { p: XY; heading_deg: number } | null;
  /** #69: the calibration tie, the map point the API scales the scan about; null when the dog was never placed. */
  cal?: { map: XY; heading_deg: number; at?: string } | null;
  follow: {
    active?: boolean; i?: number; n?: number; dist_px?: number | null; err_deg?: number | null; stopped_at?: number | null;
    error?: string | null; done?: boolean; reached?: number[]; planned?: XY[][]; trace?: XY[];
  };
}
/** GET /dog/grid. `hits` is S13's, not on main yet: without it the grid is drawn in one ink. */
export interface GridPx {
  n: number; cells_px: XY[]; cell_px: number | null; threshold: number; frames: number; source: string | null;
  why?: string; error?: string; cb_errors?: number; hits?: number[];
  /** #70: each cell's highest measured layer in metres, parallel to cells_px (null: none at or above the floor); absent
   *  with top_why for a grid saved with no height profile. */
  top_m?: Array<number | null>; top_why?: string;
}
/** GET /dog/floorplan. segments_px rows are [x0, y0, x1, y1, n]. */
export interface FloorPlanPx {
  ok?: boolean; segments_px: number[][]; classes: Record<string, number>; class_px: Record<string, XY[]>;
  cell_px?: number; ms?: number; source?: string | null; why?: string; error?: string;
  /** S13: measured tops in metres, one per segments_px entry and per class_px cell; absent for a grid with no height profile. */
  segments_top_m?: Array<number | null>; class_top_m?: Record<string, Array<number | null>>;
}
/** GET /dog/lidar. `known` is S13's. `z_m` (#67): each point's measured height in metres, parallel to points_px (the
 *  highest z of its column inside the 0.10-1.00 m band, rounded to 0.05); absent with no frame. */
export interface LidarPx { on: boolean; n: number; age_ms?: number | null; frame?: { id?: string } | null; points_px: XY[]; why?: string; error?: string; known?: boolean[]; z_m?: Array<number | null> }
/** GET /routines (#71): the named routes, and the one whose path, stops and actions are the map's now (else null). */
export interface RoutinesJson { routines: Array<{ name: string; dots: number; stops: number[]; saved_at: string }>; loaded: string | null }
/** GET /people (#72): the group's name (WTDD_CHAT_NAME, else null with group_why) and the housemates' first names; never a handle. */
export interface PeopleJson { group: string | null; group_why?: string; people: Array<{ name: string }>; why?: string }
/** GET /integrations (#72): one entry each for unitree, lidar, hue, tuya, imessage, jev, openrouter and ledger. `ok` null is
 *  unknown (never connected, switched off, no row, a stub row); `as_of` is when the evidence is from; `key_set` (jev and
 *  openrouter only) says a key is set, never the key. Neither route connects the dog or calls the network. */
export interface IntegrationsJson { checked_at: string; integrations: Array<{ name: string; ok: boolean | null; detail: string; as_of: string | null; key_set?: boolean }> }
/** GET /sessions (#75): one line per run, newest first, each number the one /record?shift=<id> counts. A bare array. */
export type Sessions = Array<{ shift_id: string; start: string | null; end: string | null; rows: number; stops: number; flags: number; signed: boolean; signed_by: string | null; stub_rows: number; in_force: boolean }>;
/** GET /images (#73): the photos a run's rows name, in time order; the bytes are behind /pictures/<file>. `missing`: the
 *  file is not in the pictures folder. `replaced`: a newer look wrote the same name after the row, so the bytes at `url`
 *  are not this row's. `why` counts both, or says why the list is empty. */
export interface RunImage { file: string; url: string; ts: string; kind: "look" | "ask" | "scout" | "blob"; stop: number | null; trigger: string | null; caption: string | null; shift_id: string; ok: boolean; missing: boolean; replaced: boolean }
export interface ImagesJson { shift: string; images: RunImage[]; n: number; why?: string }
/** GET /dog/objects. */
export interface ObjectsPx {
  n: number; windows?: number; fov_deg?: number; source?: string; why?: string; error?: string;
  objects: Array<{ id: string; label: string; p: number; message?: string | null; message_source?: string; thumb?: string; pos_px?: XY | null; stale?: boolean; why?: string }>;
}
/** GET /dog/blobs (16): Jev's names for the floor plan's runs and blobs, pinned where they are; WTDD_BLOBS serves a fixture. */
export interface BlobsPx {
  labels: Array<{ blob_id: string; kind: string; label: string | null; p: number | null; pos_px?: XY | null; source?: string; error?: string }>;
  source: string | null; why?: string; error?: string;
}
/** GET /dog/scale. */
export interface Scale { px_per_m: number; source: string; error?: string }
/** GET /map (ui/map.json). */
export interface MapJson {
  path: XY[]; stops?: number[]; _version?: number;
  actions?: Record<string, { look?: string; say?: boolean; ask?: boolean }>;
  /** The house plan's rooms, drawn by hand in the same pixel frame. */
  rooms?: Array<{ name: string; poly: XY[] }>;
  lights?: Array<{ id: string; kind: "dot" | "line"; pts: XY[]; label?: string; name?: string }>;
  /** 04's drawn zones; 19's scout zones add source "scout", `by` ("auto" or a person's name), and for an auto zone its label and p. */
  zones?: Array<{ name: string; label?: string; poly: XY[]; nogo?: boolean; source?: string; by?: string; p?: number; app?: string }>;
}
/** GET /dog/scout (19): the scout's auto zones and proposals, the map version they were served from, failed model calls. */
export interface Scout {
  n: number; zones: NonNullable<MapJson["zones"]>; proposals: unknown[]; _version?: number; source?: string; why?: string;
  failed?: Array<{ stage?: string; error: string; kind?: string; object_id?: string; ts?: string }>;
}
/** GET /record?shift=<id> (item 10, S13's route): one shift's record, exactly `python -m wtdd.record --shift <id>`'s JSON.
 *  flags[].to, flags[].resolved.by and corrections[].by are raw handles: the page redacts the whole record. */
export interface RecordJson {
  shift_id: string; rows: number; stamped: number; posts: number; stub_rows: number;
  window: { from: string; to: string; closed_by: string | null };
  stops: Array<{ n: number; index: number | null; ts: string; kind: string | null; ok: boolean; error: string | null; sentence: string | null;
    person: boolean | null; out_of_place: string[] | null; pinged: boolean; correction: string | null }>;
  flags: Array<{ ts: string; trigger: string; stop: number | null; to: string; text: string;
    /** B1: the flag's final outcome. verdict and by/text/ts from the newest verdict; acked_ms the first reply's clock;
     *  closed_ms only when that final row carries one (a hold later handled). null: unanswered. */
    resolved: { by: string; text: string; verdict: string; acked_ms: number | null; closed_ms?: number; ts: string } | null }>;
  corrections: Array<{ ts: string; by: string; text: string; said: string; acked_ms: number | null }>;
  acked_median_ms: number | null;
  refusals: Array<{ ts: string; tool: string; error: string }>;
  failures: Array<{ ts: string; tool: string; error: string }>;
  signed: { by: string; at: string } | null;
  after_signature: unknown[];
}
/** GET /record/shifts. */
export interface Shifts { shifts: string[]; current: string }
/** GET /evals: evals.json, written only by `python -m wtdd.evals --write` ({} when there is none). */
export interface Evals { written?: string; rows?: Array<{ scenario: string; trial: number; grade: "pass" | "fail" | "unsafe"; why?: string; detail?: string; ran?: string }> }
/** GET /field: the running walk, {} when idle. */
export interface Field { p?: XY; here?: string; levels?: Record<string, number>; stop?: number | null }
/** GET /chat: the listener's heartbeat. */
export interface Chat { alive: boolean; armed: boolean | null; pending: unknown; group: string }
/** GET /shift. */
export interface Shift { shift_id: string; source: string }
/** One ledger row as GET /ledger serves it. */
export interface ApiRow {
  ts: string; tool: string; ok: boolean; latency_ms: number; agent?: string; cached?: boolean; source?: string;
  args?: Record<string, unknown>; state_before?: unknown; state_after?: unknown; response_or_error?: unknown;
}

/**
 * S10: the receipts are filmed. A phone handle or an email reads "a member", and a chat id's service prefix goes with it
 * ("iMessage;-;+1555…" and B10's "iMessage;-;a member" both read "a member"), so no raw id is left on screen. Dates,
 * coordinates and numbers pass.
 */
export const redact = (s: string) => s
  .replace(/(?:[A-Za-z]+;[-+];)?(?:\+\d{7,15}|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|a member\b)/g, "a member")
  .replace(/[A-Za-z]+;\+;[\w-]+/g, "the group");   // a group chat's raw id (iMessage;+;chat…, any;+;<hex>)
/** A whole value redacted, for the row drawer that prints args and state as JSON. */
export const redactDeep = <T,>(v: T): T => (v == null ? v : JSON.parse(redact(JSON.stringify(v))));

async function read(res: Response, what: string) {
  const text = await res.text();
  let body: unknown = null;
  try { body = JSON.parse(text); } catch { body = null; }
  const served = body && typeof body === "object" && "error" in body ? String((body as { error: unknown }).error) : null;
  if (!res.ok) throw new Error(`${what} ${res.status}: ${served ?? (text.slice(0, 200) || res.statusText)}`);
  if (served) throw new Error(`${what}: ${served}`);
  if (body === null) throw new Error(`${what}: not JSON`);
  return body;
}

export async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`, { cache: "no-store" });
  return read(res, `GET ${path}`) as Promise<T>;
}

/**
 * A POST. The reply is returned as served, with ok false and the reason when the route or the tool failed, so the
 * caller shows FAILED and the reason. It never throws.
 */
export async function post(path: string, body: unknown = {}, timeoutMs = 15000): Promise<{ ok: boolean; error?: string; [k: string]: unknown }> {
  try {
    const res = await fetch(`/api${path}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),   // so a busy button can never hang on a request that never answers
    });
    const text = await res.text();
    let out: Record<string, unknown> = {};
    try { out = JSON.parse(text); } catch { out = {}; }
    if (!res.ok || out.ok === false || out.error) {
      const why = out.error ?? out.why;   // a refused press may carry its reason as `why` with ok false (POST /dog/floorplan)
      return { ...out, ok: false, error: `POST ${path} ${res.status}: ${String(why ?? (text.slice(0, 200) || res.statusText))}` };
    }
    return { ...out, ok: true };
  } catch (e) {
    if (e instanceof Error && e.name === "TimeoutError") return { ok: false, error: `POST ${path}: no answer in ${timeoutMs / 1000} s (it may still have run)` };
    return { ok: false, error: `POST ${path} failed: ${e instanceof Error ? e.message : String(e)}` };
  }
}

/** Polls a GET route every `ms` (the next poll starts after the last one ends). `path` null pauses it. A new `kick`
 *  reads it again now (after a POST that changes it), keeping what it shows until the answer is in. */
export function usePoll<T>(path: string | null, ms: number, kick = 0): { data?: T; error?: string } {
  const [out, setOut] = useState<{ path?: string; data?: T; error?: string }>({});
  useEffect(() => {
    if (!path) return;
    let alive = true, timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try { const data = await get<T>(path); if (alive) setOut({ path, data }); }
      catch (e) { if (alive) setOut({ path, error: e instanceof Error ? e.message : String(e) }); }
      if (alive) timer = setTimeout(tick, ms);
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [path, ms, kick]);
  return path && out.path === path ? { data: out.data, error: out.error } : {};   // a paused poll reads nothing
}
