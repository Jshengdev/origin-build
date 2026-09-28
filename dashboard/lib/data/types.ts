/**
 * Copied from wtdd-product-rig/contracts/types.ts. Added optional fields the fixtures carry (item, honest, note).
 *
 * What the Dog Doin: VIEW MODELS for the remote v2.
 *
 * These are NOT a backend contract. The backend exists: wtdd/api.py and ledger.jsonl in Jshengdev/origin-build.
 * Each type below is what one panel needs. The adapter (lib/data/api.ts) maps API responses and ledger rows
 * into these. Before writing the adapter, read wtdd/api.py and a sanitized ledger sample
 * (docs/evidence/ledger-sample-2026-09-13.jsonl) and fix any field here that does not match. The repo wins.
 *
 * Status words are the team's and appear in the UI where a feature depends on unmerged work:
 * "EXISTS on main" | "BUILT, PR #n open, not merged" | "BUILDING" | "NOT BUILT".
 */

export type ISODate = string;
export type Meters = number;
export type Source = "live" | "stub";          // "stub" = dry fixture; the UI shows the stub badge on anything it feeds
export type Status = "exists_on_main" | "built_pr" | "building" | "not_built" | "refused";

export interface Site {
  id: string; name: string; standIn: boolean;   // true for the house; the UI says "stand-in for a site"
  mode: "house" | "site";                         // item 20 mode vocabulary (BUILT, PR #14)
  timezone: string; noPlan: boolean;              // WTDD_NO_PLAN: no drawn floor plan, the dog's own map only
  note?: string;
}

/** Item 01 occupancy grid, served as [ix, iy, count, zmask]. Drawn on the heat ramp by count. */
export interface Grid { cellMeters: number; frame: "odometry"; frames: number; cells: Array<[number, number, number, number]>; threshold: number; honest?: string; }

/** Item 15 floor plan: segments in meters; geometry, not AI. */
export interface FloorPlan { segments: Array<[Meters, Meters, Meters, Meters]>; classes: Record<string, number>; constantsVerified: boolean; honest?: string; }

export interface Zone {
  id: string; name: string; kind: "nogo" | "proposed";
  polygon: Array<[Meters, Meters]>;
  drawnBy: "person" | "dog";
  status: "rule" | "awaiting_tap";                 // a proposal never refuses anything until a person taps it
  item?: string; honest?: string;
}

export interface Device {
  id: string; kind: "body" | "light" | "camera";
  name: string; status: "online" | "offline" | "stale" | "error";
  integration: string; position: [Meters, Meters]; headingDeg?: number;
  placedBy?: "hand" | "click";                     // lamps and the camera are placed by hand; not measured
  on?: boolean; brightness?: number;
  model?: string; item?: string; honest?: string;
  vitals?: { batteryPct: number; tempC: number | null; faults: string[]; stateAgeMs: number; videoAgeMs: number; lidarAgeMs: number }; // item 24
}

export interface Person { id: string; name: string; role: "on_call" | "group"; channel: "imessage_1to1" | "imessage_group" | "sms"; note?: string; }

/** `look` is unset for a stop the map gives no action (GET /map actions). */
export interface Stop { id: string; index: number; name: string; position: [Meters, Meters]; look?: "nod" | "level" | "sit"; intruderCheck?: boolean; }

export interface Route {
  id: string; name: string; source: string;
  status: Status;                                  // taught = exists_on_main; tapped/planned = built_pr (item 21); refused (item 04)
  polyline: Array<[Meters, Meters]>; stopIds?: string[];
  legs?: Array<{ from: string; to: string; ok: boolean }>;
  why?: string;                                    // for refused routes, the refusal row's text
  item?: string; waypointEveryM?: number;
}

export interface Roster {                          // item 08 (BUILT, PR #2)
  night: string; item?: string; stopsToBody: string[]; cameraToZone: Record<string, string>; onCall: string;
  quote: { stops: number; nights: number; pricePerStopNight: number; total: number; currency: string; label: string };
  guardShift: { value: number; unit: string; source: string; label: string };
}

/** One ledger row as the receipts panel shows it. Confirm field names against ledger.jsonl. */
export interface LedgerRow {
  ts: ISODate; tool: string; ok: boolean; latency_ms: number;
  cached?: boolean; source?: Source;
  stop?: string; item?: string;
  args?: Record<string, unknown>; state_before?: Record<string, unknown>; state_after?: Record<string, unknown>;
  error?: string;
}

export interface Look {
  stop: string; ts: ISODate; image: string;
  pins: Array<{ label: string; p: number; position: [Meters, Meters] }>;   // item 07 object pins
  sentence: string;                                                      // the vision model's words
}

export interface MorningPage {                    // item 10 (BUILT, PR #13)
  shift: string; banner?: string;
  stops: Array<{ stop: string; result: string; resolvedBy?: string | null; ackedMs?: number }>;
  refusals: Array<{ route: string; why: string }>;
  signature: { status: "unsigned" } | { status: "signed"; by: string; at: ISODate };
  secondSignature: string;
  honest?: string;
}

export interface Evals { label: string; grades: Array<{ scenario: string; result: "pass" | "fail" | "unsafe"; why?: string }>; }

export interface Integration { id: string; what: string; status: string; }

export interface Fixture<T> { _note: string; source: "stub"; data: T; }
