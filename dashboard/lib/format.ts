/** Formatting only. Nothing here derives a new number; it changes how a served value is written. */

/** "23:01:24" in the site's timezone. Mono on screen. */
export function clock(ts: string, timeZone = "America/Los_Angeles") {
  return new Date(ts).toLocaleTimeString("en-US", { timeZone, hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** "7:02 PM" for meta lines. */
export function shortTime(ts: string, timeZone = "America/Los_Angeles") {
  return new Date(ts).toLocaleTimeString("en-US", { timeZone, hour: "numeric", minute: "2-digit" });
}

/** A served millisecond age written in the unit a person reads: "400 ms", "6.0 s". */
export function age(ms: number) {
  return ms < 1000 ? { value: String(ms), unit: "ms" } : { value: (ms / 1000).toFixed(1), unit: "s" };
}

/** "Sep 26" */
export function day(ts: string, timeZone = "America/Los_Angeles") {
  return new Date(ts).toLocaleDateString("en-US", { timeZone, month: "short", day: "numeric" });
}

/** "Sep 26, 4:00 PM" */
export function dayTime(ts: string, timeZone = "America/Los_Angeles") {
  return `${day(ts, timeZone)}, ${shortTime(ts, timeZone)}`;
}

/** "13:49" from two timestamps: how long a session ran. */
export function duration(from: string, to: string) {
  const s = Math.max(0, Math.round((Date.parse(to) - Date.parse(from)) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
