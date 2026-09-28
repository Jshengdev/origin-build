"use client";
/**
 * The dog's two switches on Overview, beside Stop and Walk (Johnny, 17:00: "all the functionality of the dog at a glance";
 * the head's scope: a LiDAR switch and a drive switch).
 *
 * LiDAR: POST /dog/lidar {on}; the switch shows GET /dog/lidar's served `on`, never an optimistic one, and a refusal is a
 * FAILED line. A page never connects the dog on its own; a press does: {on: true} while disconnected is the first command, which connects it (the head: a cold start).
 *
 * Drive: S1's rules from today's remote (origin-build ui/index.html 179-208), ported as they are:
 *   disarmed on every page load; W A S D Q E drive only while armed; never while typing in an input, textarea, select or
 *   contenteditable, never with ctrl, cmd or alt, never on key repeat; Cmd going down or up, or a context menu, releases
 *   every key (macOS loses keyups under Cmd); a held key refreshes POST /dog/drive every 200 ms
 *   (the API stops the dog 0.6 s after the last refresh); the same speeds (0.3 m/s, 0.5 rad/s); letting go of the last key
 *   sends one POST /dog/stop; leaving the tab (blur, or the page hidden) disarms, releases every key and sends ONE stop
 *   only if a key was held; disarming releases every key. Stop (components/live/stop.tsx) is never gated by any of this.
 *
 * Scale (S5b, today's remote's #admin slider; the head's green light, Johnny aligning the saved scan to the plan):
 * see ScaleSlider. It sits in the map's actions, beside "Place the dog".
 */
import { useEffect, useRef, useState } from "react";
import { ActionButton } from "@/components/wtdd";
import { post, type FieldJson, type LidarPx, type Scale } from "@/lib/data/api";
import type { Result } from "@/components/live/stop";

const VEL: Record<string, [number, number, number]> = { w: [0.3, 0, 0], s: [-0.3, 0, 0], a: [0, 0.3, 0], d: [0, -0.3, 0], q: [0, 0, 0.5], e: [0, 0, -0.5] };

export function useDrive(connected: boolean) {
  const keys = useRef(new Set<string>());
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const armedRef = useRef(false);
  const [armed, setArmed] = useState(false);

  const sendDrive = () => {
    const v: [number, number, number] = [0, 0, 0];
    for (const k of keys.current) { const kv = VEL[k]; if (kv) { v[0] += kv[0]; v[1] += kv[1]; v[2] += kv[2]; } }
    return v.some(Boolean) ? post("/dog/drive", { x: v[0], y: v[1], z: v[2] }, 3000) : post("/dog/stop", {}, 3000);
  };
  const press = (k: string) => {
    if (!VEL[k] || keys.current.has(k)) return;
    keys.current.add(k);
    if (!timer.current) { sendDrive(); timer.current = setInterval(sendDrive, 200); }
  };
  const release = (k: string) => {
    keys.current.delete(k);
    if (!keys.current.size && timer.current) { clearInterval(timer.current); timer.current = null; post("/dog/stop", {}, 3000); }
  };
  const releaseAll = () => {
    const held = keys.current.size > 0 || timer.current !== null;
    keys.current.clear();
    if (timer.current) { clearInterval(timer.current); timer.current = null; }
    if (held) post("/dog/stop", {}, 3000);
  };
  const arm = (on: boolean) => { armedRef.current = on; setArmed(on); if (!on) releaseAll(); };

  useEffect(() => {
    const typing = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      return !!t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
    };
    // macOS: while Cmd is down, Chrome and Safari do not deliver keyup for the other keys, so a key let go under Cmd would
    // stay "held" and keep driving. Cmd going down or up, or a context menu opening, releases every key (and stops one held).
    const kd = (e: KeyboardEvent) => {
      if (e.key === "Meta" || e.metaKey) { releaseAll(); return; }
      if (!armedRef.current || typing(e) || e.repeat || e.ctrlKey || e.altKey) return;
      press(e.key.toLowerCase());
    };
    const ku = (e: KeyboardEvent) => { if (e.key === "Meta") { releaseAll(); return; } release(e.key.toLowerCase()); };
    const menu = () => releaseAll();
    const off = () => arm(false);   // the tab lost focus: nothing held stays held
    const vis = () => { if (document.hidden) off(); };
    window.addEventListener("keydown", kd); window.addEventListener("keyup", ku);
    window.addEventListener("blur", off); document.addEventListener("visibilitychange", vis);
    window.addEventListener("contextmenu", menu);
    return () => {
      window.removeEventListener("contextmenu", menu);
      window.removeEventListener("keydown", kd); window.removeEventListener("keyup", ku);
      window.removeEventListener("blur", off); document.removeEventListener("visibilitychange", vis);
      releaseAll();   // leaving the page: nothing keeps driving
    };
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  // the dog dropped: disarm, as leaving the tab does (keys cannot reach a dog that is not there)
  useEffect(() => {
    if (connected || !armedRef.current) return;
    const t = setTimeout(() => arm(false), 0);
    return () => clearTimeout(t);
  }, [connected]);   // eslint-disable-line react-hooks/exhaustive-deps

  const button = (
    <ActionButton intent={armed ? "person" : "secondary"} size="sm" aria-pressed={armed} disabled={!connected && !armed}
      title={armed ? "W A S D to move, Q E to turn · leaving the tab disarms" : connected ? "Arm the keyboard to drive (W A S D, Q E)" : "The dog is not connected"}
      onClick={() => arm(!armed)}>
      {armed ? "Drive armed · WASD QE" : "Drive off"}
    </ActionButton>
  );
  return { armed, button };
}

/** The LiDAR switch: the served state, a POST to change it, the reply as a result line. */
export function LidarSwitch({ lidar, connected, onResult }: { lidar?: LidarPx; connected: boolean; onResult: (r: Result) => void }) {
  const [busy, setBusy] = useState(false);
  const on = !!lidar?.on;
  const flip = async () => {
    setBusy(true);
    const r = await post("/dog/lidar", { on: !on });
    setBusy(false);
    onResult({ what: `LiDAR ${on ? "off" : "on"}`, ok: r.ok, error: r.error });   // the switch itself follows GET /dog/lidar
  };
  return (
    <ActionButton intent="secondary" size="sm" aria-pressed={on} disabled={busy}
      title={connected ? "POST /dog/lidar; the switch shows the served state" : "POST /dog/lidar {on: true}: the first press connects the dog"} onClick={flip}>
      {on ? "LiDAR on" : "LiDAR off"}
    </ActionButton>
  );
}

/** Pixels per metre on the floor plan, slid until the LiDAR's walls sit on the drawn ones. It shows GET /dog/scale's served
 *  px_per_m and its source. POST /dog/scale goes on release only (the native change event, not every tick), over 60–180
 *  like today's remote; then the page reads the scale back, refused or not, and shows the served value. Where the hand is
 *  while sliding is marked "→", never shown as the scale. A refusal is the page's FAILED line. */
export function ScaleSlider({ scale, busy, onCommit }: { scale: { data?: Scale; error?: string }; busy: boolean; onCommit: (pxPerM: number) => Promise<void> }) {
  const [draft, setDraft] = useState<number | null>(null);
  const el = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const i = el.current;
    if (!i) return;
    const f = () => { onCommit(+i.value).then(() => setDraft(null)); };
    i.addEventListener("change", f);
    return () => i.removeEventListener("change", f);
  });
  const s = scale.data;
  if (!s) return <span className={`font-mono text-[12px] ${scale.error ? "text-signal-alert" : "text-muted-foreground"}`}>{scale.error ? `scale FAILED · ${scale.error}` : "scale …"}</span>;
  return (
    <label className="flex items-center gap-2 font-mono text-[12px] text-muted-foreground"
      title="Pixels per metre on the floor plan: slide until the LiDAR's walls sit on the drawn ones. Set on release (POST /dog/scale), then read back.">
      scale
      <input ref={el} type="range" min={60} max={180} step={0.5} value={draft ?? s.px_per_m} disabled={busy} aria-label="Map scale, pixels per metre"
        onChange={(e) => setDraft(+e.target.value)} className="w-32 accent-foreground" />
      <span className="text-foreground">{s.px_per_m} px/m</span>· {s.source}{draft != null && draft !== s.px_per_m && <span className="text-foreground">→ {draft}</span>}
    </label>
  );
}

/** Lights follow the dog (Johnny: "lights on should just be a toggle"). On starts the proximity field on the dog's believed
 *  position, the old remote's "lights follow the dog" (POST /tools/walk_path {source: "dog", follower: false, act: false}):
 *  wherever the dog goes, walked or driven, the lights near it come up and the ones it leaves go dark. Off is POST
 *  /field/stop, which ends it dark. The switch shows GET /field, never an optimistic state. The on call stays open as long
 *  as the lights follow (the tool answers when the field ends), so its answer is the result line. Needs the dog located.
 *  It owns only its own field (follower false): while a walk it did not start runs (a chat round's), it reads "a walk is
 *  running" and posts nothing, so it can never stop a round (field.STOP is shared). While on, it says to turn it off
 *  before a chat round: a round's own walk is refused while this field runs (the head's run-sheet rule for tonight). */
export function LightsSwitch({ field, connected, calibrated, onResult }: { field?: FieldJson; connected: boolean; calibrated: boolean; onResult: (r: Result) => void }) {
  const [busy, setBusy] = useState(false);
  const on = !!field?.p && field.follower === false;   // its own follow-the-dog field only
  const other = !!field?.p && !on;                     // a walk it did not start (a chat round's): hands off
  const flip = async () => {
    setBusy(true);
    if (on) {
      const r = await post("/field/stop", {});
      setBusy(false);
      if (!r.ok) onResult({ what: "Lights off", ok: false, error: r.error });
      return;
    }
    const running = post("/tools/walk_path", { source: "dog", follower: false, act: false }, 6 * 3600 * 1000);   // open until the field ends
    setTimeout(() => setBusy(false), 1500);   // then the switch follows GET /field
    const r = await running;
    setBusy(false);
    const out = (r.result ?? {}) as { seconds?: number; writes?: number; errors?: number };
    const said = [out.seconds != null && `${out.seconds} s`, out.writes != null && `${out.writes} writes`, out.errors != null && `${out.errors} errors`].filter(Boolean).join(" · ");
    onResult(r.ok ? { what: `Lights followed the dog${said ? ` · ${said}` : ""}`, ok: true } : { what: "Lights on", ok: false, error: r.error });
  };
  const why = !connected ? "The dog is not connected" : !calibrated ? "Calibrate first: the lights follow where the dog is believed to be" : undefined;
  if (other) return (
    <ActionButton intent="secondary" size="sm" disabled title="A walk this switch did not start owns the lights (a chat round): it ends on its own or with Stop">Lights · a walk is running</ActionButton>
  );
  return (
    <span className="flex items-center gap-2">
      {on && <span className="text-[12px] text-muted-foreground">turn off before a chat round</span>}
      <ActionButton intent="secondary" size="sm" aria-pressed={on} disabled={busy || (!on && !!why)}
        title={on ? "POST /field/stop: the lights go dark" : why ?? "POST /tools/walk_path: the lights follow the dog, walked or driven"} onClick={flip}>
        {on ? "Lights on" : "Lights off"}
      </ActionButton>
    </span>
  );
}
