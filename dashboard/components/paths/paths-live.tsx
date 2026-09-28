"use client";
/**
 * Paths on the live API (V2 of the live-feature map, wtdd-product-rig/contracts/LIVE-FEATURE-MAP.md): what today's
 * remote does and no more. Tap dots to draw the path (tap a dot to take it out), make a dot a stop, draw a no-go zone
 * corner by corner and close it, clear every no-go zone, save, and walk the route.
 *
 * Edits stay on the page until "Save" posts the whole map (POST /map, the way ui/index.html does); a refused save shows
 * FAILED with the API's reason and the edit stays. 04's guard is kept verbatim: no save while a zone is being drawn.
 * "Walk the route" needs the saved map, so it waits for a save; it walks with the checkpoint look (components/live/
 * walk-route.tsx): at each stop the dog does that stop's action, and the Stops card sets it: "Look up & down" (look tilt,
 * else level) and "Post to the group" (say). A stop with no action looks up and down and does NOT post (the walk saves
 * that before it starts). No stops: a straight walk, POST /dog/follow.
 * 19's auto zones (a hazard the scout named at p >= the threshold) are on the map at once; a person dismisses one in
 * their own name (POST /dog/scout), the way today's remote does. Its proposals (the feed opens none now) are not drawn.
 * "Ask here" on a stop (the head, for the live film): the intruder check, map.json actions["<path index>"].ask, which
 * listen.py's look_and_say reads at that stop (a person in frame: "who dis?!" and the round holds for the answer). It
 * saves at once through the same POST /map with the served map's _version (the 409 guard), keeps the stop's other keys
 * (look, say), shows the served state, and a refused save is the page's FAILED line. Not while an edit is unsaved.
 */
import { useState } from "react";
import { Input } from "@/components/ui/input";   // stock shadcn
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";   // stock shadcn, as Settings uses it
import { ActionButton, Module, SignalChip } from "@/components/wtdd";
import { PageActions } from "@/components/shell/page-header";
import { TwinMap } from "@/components/twin/twin-map";
import { useLiveMap, zoneName } from "@/components/twin/use-live-map";
import { post, redact, usePoll, type MapJson, type Scout, type XY } from "@/lib/data/api";
import { Results, useStop } from "@/components/live/stop";
import { useWalkRoute, WalkProgress } from "@/components/live/walk-route";

type Tool = "dots" | "stops" | "zone";
/** The chosen tool in ink, the rest on surface: stock "on" is accent, 1.2:1 on surface and the same as hover. */
const TOOL_ON = "px-3 text-[13px] data-[state=on]:bg-primary data-[state=on]:text-primary-foreground";
type Result = { what: string; ok: boolean; error?: string } | null;
/** A stop's look in today's remote's words (ui/index.html's stop label). */
const LOOK: Record<string, string> = { tilt: "nod", level: "level", sit: "look up" };

const HINT: Record<Tool | "none", string> = {
  dots: "Tap the floor to add a dot at the end. Tap a dot to take it out.",
  stops: "Tap a dot to make it a stop, where the dog pauses and looks. Tap it again to make it a dot.",
  zone: "Tap the corners of a zone the dog must never enter, then close it.",
  none: "Pick a tool to change the path or the zones.",
};

export function PathsLive() {
  const [draft, setDraft] = useState<MapJson | null>(null);   // the unsaved edit; null shows GET /map as served
  const [tool, setTool] = useState<Tool | null>(null);
  const [corners, setCorners] = useState<XY[]>([]);
  const [result, setResult] = useState<Result>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<MapJson | null>(null);
  const { dog, walking, props, map, served, notes, field } = useLiveMap(draft, false, saved);
  const { stopped, button: stopButton } = useStop();   // anywhere a walk starts, it can be stopped
  const scout = usePoll<Scout>("/dog/scout", 2000);
  const [by, setBy] = useState(() => (typeof window === "undefined" ? "" : localStorage.getItem("wtdd.scout.by") ?? ""));
  const [zoneErr, setZoneErr] = useState<Record<string, string>>({});
  const [tried, setTried] = useState(false);   // the name field turns red only after a Dismiss without a name, never on arrival
  // A second save within seconds must carry the _version the first one got back (today's remote keeps it), or the API
  // refuses it as a stale page (409): `served` is the saved map until the poll catches up.
  const base = draft ?? served;
  const edit = (f: (m: MapJson) => MapJson) => { if (base) setDraft(f(structuredClone(base))); };

  const nogo = (base?.zones ?? []).filter((z) => z.nogo === true);
  const dots = base?.path ?? [];

  const tapFloor = (xy: XY) => {
    const p: XY = [Math.round(xy[0]), Math.round(xy[1])];
    if (tool === "dots") edit((m) => ({ ...m, path: [...m.path, p] }));
    if (tool === "zone") setCorners((c) => [...c, p]);
  };
  const tapDot = (i: number) => {
    if (tool === "dots") edit((m) => ({   // today's remote: the stops after it move down by one
      ...m, path: m.path.filter((_, j) => j !== i), stops: (m.stops ?? []).filter((j) => j !== i).map((j) => (j > i ? j - 1 : j)),
    }));
    if (tool === "stops") edit((m) => {
      const st = new Set(m.stops ?? []);
      if (st.has(i)) st.delete(i); else st.add(i);
      return { ...m, stops: [...st].sort((a, b) => a - b) };
    });
  };
  const closeZone = () => {
    const zones = base?.zones ?? [];
    let n = zones.filter((z) => z.nogo === true).length + 1;
    while (zones.some((z) => z.name === `nogo-${n}`)) n++;   // the name stays unique: it is the refusal row's zone
    edit((m) => ({ ...m, zones: [...(m.zones ?? []), { name: `nogo-${n}`, label: `no-go ${n}`, poly: corners, nogo: true }] }));
    setCorners([]);
    setTool(null);
  };

  const save = async (m: MapJson | null | undefined, what: string) => {
    if (!m) return;
    if (tool === "zone" && corners.length) {   // 04's guard, its words
      setResult({ what, ok: false, error: "not saved: a no-go zone is still being drawn: press close zone (or clear), then save" });
      return;
    }
    setBusy(true);
    const r = await post("/map", m);
    setBusy(false);
    setResult(r.ok ? { what, ok: true } : { what, ok: false, error: r.error });
    if (r.ok) { setSaved({ ...m, _version: r._version as number | undefined }); setDraft(null); setTool(null); }
  };
  const clearNogo = () => save(base && { ...base, zones: (base.zones ?? []).filter((z) => z.nogo !== true) }, "Clear no-go");   // S4: saved at once; lighting zones stay
  const dismiss = async (name: string) => {   // 19: an auto zone off the map, in a person's name, against the map it was served from
    if (!by.trim()) { setTried(true); return; }
    setBusy(true);
    const r = await post("/dog/scout", { id: name, action: "dismiss", by: by.trim(), _version: scout.data?._version });
    setBusy(false);
    setZoneErr((e) => ({ ...e, [name]: r.ok ? "" : `dismiss ${r.error}` }));
  };
  const askHere = async (i: number, n: number, on: boolean) => {   // saved at once, against the map as served
    if (!served) return;
    const k = String(i), actions = { ...(served.actions ?? {}) }, a = { ...(actions[k] ?? {}) };
    if (on) actions[k] = { look: "tilt", ...a, ask: true };
    else { delete a.ask; if (Object.keys(a).length) actions[k] = a; else delete actions[k]; }
    const what = on ? `Ask here · stop ${n}` : `No ask · stop ${n}`;
    setBusy(true);
    const r = await post("/map", { ...served, actions });
    setBusy(false);
    setResult(r.ok ? { what, ok: true } : { what, ok: false, error: r.error });
    if (r.ok) setSaved({ ...served, actions, _version: r._version as number | undefined });
  };
  const walkRoute = useWalkRoute(field.data, setResult, setSaved);
  const walk = () => walkRoute.start("Walk the route", served);
  // a stop's action, saved at once against the map as served (like Ask here): "Look up & down" and "Post to the group"
  const setAction = async (i: number, what: string, patch: { look?: string; say?: boolean }) => {
    if (!served) return;
    const k = String(i), actions = { ...(served.actions ?? {}) };
    actions[k] = { look: "tilt", ...(actions[k] ?? {}), ...patch };
    setBusy(true);
    const r = await post("/map", { ...served, actions });
    setBusy(false);
    setResult(r.ok ? { what, ok: true } : { what, ok: false, error: r.error });
    if (r.ok) setSaved({ ...served, actions, _version: r._version as number | undefined });
  };

  const d = dog.data;
  return (
    <div className="flex flex-col gap-4">
      <PageActions>
        {dog.error && <SignalChip tone="alert">Dog · FAILED {redact(dog.error)}</SignalChip>}
        {draft && <SignalChip tone="neutral">Not saved</SignalChip>}
        <WalkProgress field={field.data} follow={dog.data?.follow ?? {}} stops={served?.stops ?? []} />
        <span className="ml-auto flex items-center gap-2">
          {draft && <ActionButton intent="quiet" disabled={busy} onClick={() => { setDraft(null); setCorners([]); setTool(null); }}>Discard</ActionButton>}
          <ActionButton intent="secondary" disabled={busy || !draft} onClick={() => save(draft, "Save")}>Save</ActionButton>
          {stopButton}
          <span className="text-[12px] text-muted-foreground">looks and photographs at each stop</span>
          <ActionButton intent="primary" disabled={busy || walkRoute.starting || !!draft || !d?.calibrated || walking || dots.length < 2}
            title={draft ? "Save first" : dog.error ? "The dog's state did not load" : !d?.calibrated ? "Place or drag the dog on Overview's map first" : dots.length < 2 ? "Draw at least two dots" : walking ? "Walking" : "POST /tools/walk_path: the route, a look at each stop, the lights following"}
            onClick={walk}>
            Walk the route
          </ActionButton>
        </span>
      </PageActions>

      <div className="grid grid-cols-12 gap-4">
        <Module title="Site map" meta="the house, a stand-in for a site" size="auto"
          className="col-span-12 lg:col-span-8 [&>[data-slot=card-content]]:flex [&>[data-slot=card-content]]:flex-1">
          <TwinMap {...props} mode="plan2d" live={props.live && { ...props.live, onWaypoint: tool === "dots" || tool === "stops" ? tapDot : undefined }}
            onMapClick={tool === "dots" || tool === "zone" ? tapFloor : undefined}
            onStopClick={tool === "dots" || tool === "stops" ? (id) => tapDot(Number(id.replace("stop-", ""))) : undefined}
            draft={tool === "zone" ? corners : undefined}
            className="h-auto min-h-[820px] flex-1" />
        </Module>

        <div className="col-span-12 flex flex-col gap-4 lg:col-span-4">
          {/* Results sit in this column, never above the map: a line appearing after a save must not move the map
              under a finger that is about to tap again (worker's live check). */}
          {[...stopped, result].some(Boolean) && <div className="flex flex-col gap-1"><Results rows={[...stopped, result]} />{walkRoute.lightsOff}</div>}
          {/* each map layer's served status and every FAILED, outside the map (the map keeps only its legend) */}
          <div className="flex flex-col gap-0.5 font-mono text-[11px] text-muted-foreground empty:hidden">{notes}</div>
          <Module title="Draw" size="auto">
            <div className="flex flex-col gap-2">
              <ToggleGroup type="single" value={tool ?? ""} variant="outline" disabled={!base}
                onValueChange={(v) => { setTool((v || null) as Tool | null); setCorners([]); }}>
                <ToggleGroupItem value="dots" className={TOOL_ON}>Tap dots</ToggleGroupItem>
                <ToggleGroupItem value="stops" className={TOOL_ON}>Stops</ToggleGroupItem>
                <ToggleGroupItem value="zone" className={TOOL_ON}>No-go zone</ToggleGroupItem>
              </ToggleGroup>
              <p className="text-[15px] leading-[22px] text-muted-foreground">{HINT[tool ?? "none"]}</p>
              {tool === "dots" && dots.length > 0 && (
                <ActionButton intent="quiet" className="self-start" onClick={() => edit((m) => ({ ...m, path: [], stops: [] }))}>Clear the path</ActionButton>
              )}
              {tool === "zone" && (
                <div className="flex gap-2">
                  <ActionButton intent="secondary" disabled={corners.length < 3} onClick={closeZone}>Close zone</ActionButton>
                  <ActionButton intent="quiet" disabled={corners.length === 0} onClick={() => setCorners([])}>Clear corners</ActionButton>
                </div>
              )}
            </div>
          </Module>

          <Module title="Stops" size="auto" error={map.error && !draft ? `FAILED ${map.error}` : undefined} loading={!map.data && !map.error}>
            {(served?.stops ?? []).length === 0 ? (
              <p className="text-[15px] text-muted-foreground">No stops saved. Pick Stops, tap a dot, then save.</p>
            ) : (
              <ul className="flex flex-col">
                {(served?.stops ?? []).map((i, n) => {
                  const entry = served?.actions?.[String(i)], a = entry ?? {};
                  const look = (a.look ?? "tilt") === "tilt", say = a.say === true;   // no action saved: looks up and down, no post (the walk saves that first)
                  return (
                    <li key={i} className="flex flex-wrap items-center gap-2 border-t border-border py-2 first:border-t-0 first:pt-0">
                      <span className="text-[13px] font-medium">Stop {n + 1}</span>
                      <span className="font-mono text-[12px] text-muted-foreground">dot {i + 1} · {entry ? `${LOOK[a.look ?? "tilt"] ?? a.look}${say ? " + post" : ", no post"}` : "default: look up & down, no post"}</span>
                      <span className="ml-auto flex items-center gap-1.5">
                      <ActionButton intent={look ? "primary" : "secondary"} size="sm" aria-pressed={look} disabled={busy || !!draft}
                        title={draft ? "Save or discard the edit first" : look ? "At this stop the dog looks down at the floor, then up at the room, and photographs. Tap for one level look instead." : "At this stop the dog takes one level look. Tap to look up and down."}
                        onClick={() => setAction(i, look ? `Level look · stop ${n + 1}` : `Look up & down · stop ${n + 1}`, { look: look ? "level" : "tilt" })}>Look up & down</ActionButton>
                      <ActionButton intent={say ? "primary" : "secondary"} size="sm" aria-pressed={say} disabled={busy || !!draft}
                        title={draft ? "Save or discard the edit first" : say ? "The photo and a sentence go to the group chat. Tap to keep it on the page only." : "The photo stays on the page (Images). Tap to also post it to the group chat."}
                        onClick={() => setAction(i, say ? `No post · stop ${n + 1}` : `Post to the group · stop ${n + 1}`, { say: !say })}>Post to the group</ActionButton>
                      <ActionButton intent={a.ask ? "primary" : "secondary"} size="sm" aria-pressed={!!a.ask} disabled={busy || !!draft}
                        title={draft ? "Save or discard the edit first" : a.ask ? "If the dog sees a person here it asks the on-call person \"who dis?!\" and waits. Tap to stop asking here." : "The intruder check: if the dog sees a person here, it asks who it is and waits for the answer"}
                        onClick={() => askHere(i, n + 1, !a.ask)}>{a.ask ? "Asks here" : "Ask here"}</ActionButton>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Module>

          <Module title="Zones" size="auto" error={map.error && !draft ? `FAILED ${map.error}` : undefined} loading={!map.data && !map.error}
            actions={nogo.length > 0 ? <ActionButton intent="secondary" size="sm" disabled={busy} onClick={clearNogo}>Clear no-go</ActionButton> : undefined}>
            {nogo.length === 0 ? (
              <p className="text-[15px] text-muted-foreground">No no-go zones. Draw one around anything the dog must never walk into.</p>
            ) : (
              <ul className="flex flex-col">
                {nogo.map((z) => (
                  <li key={z.name} className="flex flex-col gap-1.5 border-t border-border py-2 first:border-t-0 first:pt-0">
                    <span className="flex items-center gap-2">
                      <span aria-hidden className="size-3 rounded-sm border border-signal-alert bg-signal-alert-soft" />{/* an auto zone is a rule like a drawn one; its label tells it apart */}
                      <span className="text-[13px] font-medium">{zoneName(z)}</span>
                      {z.by === "auto" && (
                        <ActionButton intent="quiet" size="sm" className="ml-auto" disabled={busy || !!draft}
                          title={!by.trim() ? "Type your name first" : draft ? "Save or discard first" : "Takes it off the map, in your name"}
                          onClick={() => dismiss(z.name)}>Dismiss</ActionButton>
                      )}
                    </span>
                    {zoneErr[z.name] && <span role="alert" className="font-mono text-[12px] text-signal-alert">FAILED {redact(zoneErr[z.name])}</span>}
                  </li>
                ))}
              </ul>
            )}
            {nogo.some((z) => z.by === "auto") && (
              <label className="mt-4 flex items-center gap-2 text-[13px] text-muted-foreground">
                Your name
                <Input value={by} placeholder="required to dismiss" aria-invalid={tried && !by.trim()} className="h-8 max-w-[200px] text-[13px]"
                  onChange={(e) => { setBy(e.target.value); localStorage.setItem("wtdd.scout.by", e.target.value); }} />
              </label>
            )}
            {scout.error && <p role="alert" className="mt-2 font-mono text-[12px] text-signal-alert">scout · FAILED {scout.error}</p>}
            {scout.data?.failed?.map((f, i) => (
              <p key={i} role="alert" className="mt-2 font-mono text-[12px] text-signal-alert">
                scout · {f.stage ? `${f.stage} failed` : "model call failed"}: {redact(f.error)}{f.kind ? ` · ${f.kind}` : ""}
              </p>
            ))}
            <p className="mt-4 text-[13px] text-muted-foreground">
              It routes around every zone. A dot inside one is refused, by name. The scout adds a zone on its own only around what it names a hazard.
            </p>
          </Module>
        </div>
      </div>
    </div>
  );
}
