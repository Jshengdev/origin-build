import type { LedgerRow, Route } from "@/lib/data";
import type { MapFocus } from "@/components/twin/twin-map";

type Obj = Record<string, unknown>;
const str = (v: unknown) => (typeof v === "string" ? v : undefined);
const num = (v: unknown) => (typeof v === "number" ? v : undefined);

/** A raw id (a Hue light's uuid) is never a useful line on its own. */
const RAW_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * One line from what the row already says, plus "stand-in" when the row says it is one (cached, or source stub): the
 * DEMO_CACHE law, so a stand-in is never filmed as live. Rows from the live API carry nothing extra.
 */
export function rowDetail(r: LedgerRow): string {
  const line = rowLine(r);
  return r.cached || r.source === "stub" ? (line ? `${line} · stand-in` : "stand-in") : line;
}

/** A receipt: one ledger row, or a run of repeats shown as one; `group` is every row of the run, newest first (the row
 *  itself is the newest). */
export type ReceiptRow = LedgerRow & { group?: LedgerRow[] };

/**
 * The head, live (98 dog.cmd StopMove rows, one per drive-key release; 28 dog.calibrate, one per drag): honest, but they
 * bury the story. A run of consecutive rows with the same tool, both ok, and the same line becomes one receipt, "×N" over
 * its first–last time; its drawer lists every row, so nothing is hidden. A FAILED row is never grouped: always its own line.
 * `rows` newest first, as shown.
 */
export function groupRepeats(rows: LedgerRow[]): ReceiptRow[] {
  const out: ReceiptRow[] = [];
  for (const r of rows) {
    const last = out.at(-1);
    if (last && last.ok && r.ok && last.tool === r.tool && rowDetail(last) === rowDetail(r)) {
      if (last.group) last.group.push(r);
      else out[out.length - 1] = { ...last, group: [last, r] };
    } else out.push(r);
  }
  return out;
}

/** Its say-line, the error, the sentence, the text sent, the reply, a readable field; never a raw id. Nothing computed. */
function rowLine(r: LedgerRow): string {
  const a = (r.args ?? {}) as Obj;
  const s = (r.state_after ?? {}) as Obj;
  if (str(a.say)) return r.error ? `${a.say} · ${r.error}` : str(a.say)!;
  if (num(a.windows) != null) return `${a.windows} windows · largest nudge ${a.largest_m} m${r.error ? ` · ${r.error}` : ""}`;   // S7's pose.corrected summary
  if (r.error) return r.error;
  // the value each set, so a run of different values never reads as one repeat (the head): the scale, served before and
  // after; the pose the dog was placed at, as served back (else as sent)
  const b = (r.state_before ?? {}) as Obj, m = s.map as Obj | undefined, pose = m && Array.isArray(m.p) ? m : a;
  if (r.tool === "dog.scale" && num(s.px_per_m) != null) return `scale ${num(b.px_per_m) != null ? `${b.px_per_m} → ` : ""}${s.px_per_m} px/m`;
  if (r.tool === "dog.calibrate" && Array.isArray(pose.p)) return `placed at ${(pose.p as number[]).map((v) => Math.round(v)).join(", ")}${num(pose.heading_deg) != null ? ` · ${Math.round(pose.heading_deg as number)}°` : ""}`;
  if (str(s.sentence)) return str(s.sentence)!;
  if (str(s.reply) && num(s.acked_ms) != null) return `"${s.reply}" · acked_ms ${s.acked_ms}`;
  if (str(s.reply)) return `"${str(a.text) ?? ""}" → "${s.reply}"`;
  if (Array.isArray(s.boxes)) return (s.boxes as Array<[string, number]>).map(([l, p]) => `${l} ${p.toFixed(2)}`).join(", ");
  if (str(s.label)) return `${s.label} p ${num(s.p)?.toFixed(2)}${s.needs_person ? " · needs a person" : ""}`;
  if (num(s.wp) != null) return `wp ${s.wp} of ${s.of}`;
  // Five tools whose rows said nothing: their served fields, printed as served (no sum or rate made here).
  const cls = s.classes as Record<string, number> | undefined;
  if (cls && typeof cls === "object" && Object.keys(cls).length) return Object.entries(cls).map(([l, n]) => `${l} ${n}`).join(" · ");   // watch.boxes
  if (Array.isArray(s.out_of_place)) return [`out of place: ${s.out_of_place.join(", ") || "none"}`, str(s.detector_check)].filter(Boolean).join(" · ");   // vision.check
  if (str(s.signal)) return str(s.signal)!;   // lights.signal
  // dog.follow: how many dots it reached of the served total, and how many it passed. A served list's length is the size of
  // what the API sent, not a measurement made here; the 0-based indices themselves read as noise beside dots numbered from 1.
  if (Array.isArray(s.reached) && num(s.of) != null) {
    const passed = Array.isArray(s.passed) && s.passed.length ? ` · passed ${s.passed.length}` : "";
    return `reached ${s.reached.length} of ${s.of}${passed}${num(s.seconds) != null ? ` · ${s.seconds} s` : ""}`;
  }
  if (num(s.path_pts) != null) return `${s.path_pts} points${num(s.seconds) != null ? ` · ${s.seconds} s` : ""}`;   // dog.record
  if (str(a.text)) return `"${a.text}"`;
  if (str(a.id) && !RAW_ID.test(str(a.id)!)) return `${a.id}${num(a.bri) != null ? ` bri ${a.bri}` : ""}`;
  if (str(a.kind)) return `look: ${a.kind}`;
  if (str(a.route)) return `route ${a.route}`;
  if (str(a.to)) return `to ${a.to}`;
  if (str(a.dir)) return str(a.dir)!;
  if (str(a.action)) return str(a.action)!.replace(/_/g, " ");
  if (str(a.routine)) return str(a.routine)!;
  if (r.tool?.startsWith("routine.") && str(a.name)) return str(a.name)!;   // routine.saved / loaded / deleted: the routine's name
  if (num(a.points) != null) return `path of ${a.points} ${a.points === 1 ? "point" : "points"}`;
  if (Array.isArray(a.at)) return `at ${(a.at as number[]).map((v) => v.toFixed(1)).join(", ")} m`;
  return "";
}

/** Where a row happened, if the row says: its stop, the device it touched, or its waypoint on the taught route. */
export function rowFocus(r: LedgerRow, taught?: Route): MapFocus | null {
  const a = (r.args ?? {}) as Obj;
  const s = (r.state_after ?? {}) as Obj;
  const at = a.at;
  if (Array.isArray(at) && at.length === 2) return { kind: "point", position: at as [number, number], label: r.tool };
  if (r.stop) return { kind: "stop", id: r.stop, label: `${r.tool} · ${r.stop.toUpperCase()}` };
  if (str(a.id)) return { kind: "device", id: str(a.id)!, label: r.tool };
  const wp = num(s.wp);
  if (wp != null && taught?.polyline[wp - 1]) {
    return { kind: "point", position: taught.polyline[wp - 1], label: `WP-${String(wp).padStart(2, "0")}` };
  }
  return null;
}
