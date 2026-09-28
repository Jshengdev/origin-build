"use client";
/**
 * Overview on the live API (V1 of the live-feature map, wtdd-product-rig/contracts/LIVE-FEATURE-MAP.md): the TwinMap
 * with the dog's grid, the floor plan, the no-go zones, the live scan, the dog at its real size, the planned legs against
 * the actual route, the object pins; the body; the receipts; "Walk the route", "Resume" and "Stop".
 *
 * Every value is served (lib/data/api.ts). A route that fails shows FAILED and its reason where its layer or panel is;
 * nothing falls back to a fixture. The page computes no number: counts, sources and reasons are the API's own.
 */
import { useMemo, useState } from "react";
import { ActionButton, LiveMark, Module, SignalChip } from "@/components/wtdd";
import { PageActions } from "@/components/shell/page-header";
import { TwinMap, type MapFocus } from "@/components/twin/twin-map";
import { useLiveMap } from "@/components/twin/use-live-map";
import { Receipts } from "@/components/live/receipts";
import { groupRepeats, type ReceiptRow } from "@/components/live/ledger";
import { Camera } from "@/components/overview/camera";
import { useAsks } from "@/components/waiting/waiting-live";
import { LidarSwitch, LightsSwitch, ScaleSlider, useDrive } from "@/components/overview/controls";
import { Results, useStop, type Result } from "@/components/live/stop";
import { age } from "@/lib/format";
import { post, redact, redactDeep, usePoll, type ApiRow, type Chat, type DogState, type LidarPx, type Shift } from "@/lib/data/api";
import type { LedgerRow } from "@/lib/data";

const TZ = "America/Los_Angeles";
/** The old remote's receipts: the newest 25 rows, plus the newest pose.corrected summary pinned on top (S7). */
const RECEIPTS = 25;


export function OverviewLive() {
  const { dog, lidar, scale, fresh, walking, follow, props, notes, field, refresh } = useLiveMap();
  const d = dog.data;
  const chat = usePoll<Chat>("/chat", 3000);
  const shift = usePoll<Shift>("/shift", 5000);
  const { ledger } = useAsks();   // the shell's one GET /ledger?n=500 (every 3 s), not a second poll of its own
  const [result, setResult] = useState<Result>(null);
  const [busy, setBusy] = useState(false);
  const { stopped, button: stopButton } = useStop();
  const drive = useDrive(!!d?.connected);
  // Calibrate (Johnny, live: "calibrate ... where I'm allowed to touch the location of the dog, the angle it's looking
  // at, and the scale of the site map, and ... the toggle with lidar as well"): one switch in the map's actions; on, the
  // dog's ring and cone tip drag, and the scale, the LiDAR switch and "Place the dog" show beside it. Off is the plain view.
  const [calibrating, setCalibrating] = useState(false);
  const [placing, setPlacing] = useState(false);   // "Place the dog": the next tap on the map is where it is
  const [stretching, setStretching] = useState(false);   // "Scale by a wall": the next drag on the map sets the scale

  const act = async (what: string, calls: Array<[string, unknown]>) => {
    setBusy(true);
    for (const [path, body] of calls) {
      const r = await post(path, body);
      if (!r.ok) { setResult({ what, ok: false, error: r.error }); setBusy(false); return; }
    }
    setResult({ what, ok: true });
    setBusy(false);
  };

  /* The receipts: newest first, the newest pose.corrected pinned on top, a run of repeats as one receipt (groupRepeats),
     every string redacted (S10). Shaped once per ledger read, not on every render. */
  const { rows, apiOf } = useMemo(() => {
    const all = [...(ledger.data ?? [])].reverse();
    const corr = all.find((r) => r.tool === "pose.corrected");
    const apiOf = new Map<LedgerRow, ApiRow>();
    const shape = (r: ApiRow) => { const lr = toRow(r); apiOf.set(lr, r); return lr; };
    const rows: ReceiptRow[] = [...(corr ? [shape(corr)] : []), ...groupRepeats(all.filter((r) => r.tool !== "pose.corrected").map(shape)).slice(0, RECEIPTS)];
    return { rows, apiOf };
  }, [ledger.data]);

  /* The follower's decisions (route.decided rows) as numbered markers where the dog was when it made each (the row's
     served state_before.p), oldest first; a receipt row lights its marker: a replay of the walk, row by row. The number
     belongs to the row itself, so two decisions in the same second on the same dot never share one. */
  const poseOf = (r: { state_before?: unknown }) => {
    const p = (r.state_before as { p?: unknown } | null | undefined)?.p;
    return Array.isArray(p) && p.length === 2 ? (p as [number, number]) : null;
  };
  const decided = (ledger.data ?? []).filter((r) => r.tool === "route.decided" && poseOf(r));
  const numberOf = new Map<ApiRow, number>(decided.map((r, i) => [r, i + 1]));
  const rowNumber = new Map<LedgerRow, number | undefined>(rows.map((lr) => [lr, numberOf.get(apiOf.get(lr.group?.[0] ?? lr)!)]));   // a run: its newest row
  const decisions = decided.map((r, i) => ({ n: i + 1, position: poseOf(r)!, ok: r.ok }));
  const [focus, setFocus] = useState<MapFocus | null>(null);
  const point = (r: LedgerRow | null) => {
    const p = r && poseOf(r);
    setFocus(r && p ? { kind: "point", position: p, label: `${rowNumber.get(r) ?? ""} · ${r.tool}`.replace(/^ · /, "") } : null);
  };

  return (
    <div className="flex flex-col gap-4">
      <PageActions>
        <DogChip dog={dog.data} error={dog.error} fresh={fresh} />
        {d?.connected && (d.avoid ? <SignalChip tone="neutral">Avoid on</SignalChip> : <SignalChip tone="alert">Avoid OFF</SignalChip>)}
        <CastleChip chat={chat.data} error={chat.error} />
        {walking && <SignalChip tone="good" mark={<LiveMark />}>Walking · waypoint {follow.i} of {follow.n}</SignalChip>}
        <span className="ml-auto flex items-center gap-2">
          <LidarSwitch lidar={lidar.data} connected={!!d?.connected} onResult={setResult} />
          <LightsSwitch field={field.data} connected={!!d?.connected} calibrated={!!d?.calibrated} onResult={setResult} />
          {drive.button}
          {follow.stopped_at != null && (
            <ActionButton intent="secondary" disabled={busy} onClick={() => act("Resume", [["/dog/resume", {}]])}>Resume</ActionButton>
          )}
          {stopButton}
          <ActionButton intent="primary" disabled={busy || !d?.calibrated || walking}
            title={dog.error ? "The dog's state did not load" : !d?.calibrated ? "Calibrate first: place or drag the dog on the map" : walking ? "Walking" : "POST /dog/follow: the drawn path, every leg planned"}
            onClick={() => act("Walk the route", [["/dog/follow", {}]])}>
            Walk the route
          </ActionButton>
        </span>
      </PageActions>
      <Results rows={[...stopped, result]} />

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 flex flex-col gap-4 lg:col-span-8">
          {/* Johnny: "make where all the calibrate and stuff functionality is actually on the top of it and not on the same
              page as the site map": the map's tools and each layer's served status (every FAILED) sit in their own bar
              above it; the map keeps only its legend. */}
          <div role="toolbar" aria-label="Map tools" className="flex flex-col gap-2 rounded-xl border border-border bg-card px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <ActionButton intent={calibrating ? "person" : "secondary"} size="sm" aria-pressed={calibrating}
                title="Align the scan to the plan: drag the dog's ring to where it is and its cone tip to where it faces, and set the scale"
                onClick={() => { setCalibrating(!calibrating); setPlacing(false); setStretching(false); }}>{calibrating ? "Done calibrating" : "Calibrate"}</ActionButton>
              {calibrating && <>
                <ActionButton intent={placing ? "person" : "secondary"} size="sm" disabled={busy}
                  title={d?.connected ? "Tap the map where the dog is, then drag its cone tip to where it faces" : "Tap the map where the dog is: the first calibrate connects the dog"}
                  onClick={() => { setPlacing(!placing); setStretching(false); }}>{placing ? "Tap where the dog is" : "Place the dog"}</ActionButton>
                <ActionButton intent={stretching ? "person" : "secondary"} size="sm" disabled={busy || !scale.data || !(d?.cal?.map ?? d?.map)}
                  title={!scale.data ? "The scale did not load" : !(d?.cal?.map ?? d?.map) ? "Place the dog first" : "Press on a wall of the scan and drag it onto its line on the plan"}
                  onClick={() => { setStretching(!stretching); setPlacing(false); }}>{stretching ? "Drag a scan wall onto its line" : "Scale by a wall"}</ActionButton>
                <LidarSwitch lidar={lidar.data} connected={!!d?.connected} onResult={setResult} />
                <ScaleSlider scale={scale} busy={busy} onCommit={(v) => act("Scale", [["/dog/scale", { px_per_m: v }]]).then(refresh)} />
              </>}
              <ActionButton intent="secondary" size="sm" className="ml-auto" disabled={busy} title="POST /dog/floorplan: one run, one row"
                onClick={() => act("Floor plan", [["/dog/floorplan", { threshold: 3 }]])}>Floor plan</ActionButton>
            </div>
            <div className="flex flex-col gap-0.5 font-mono text-[11px] text-muted-foreground empty:hidden">
              {field.data?.p && (   // the lights as the field drives them, while it runs
                <span className="text-foreground">lights · {(props.live?.lamps ?? []).map((l) => `${l.label} ${field.data?.levels?.[l.id] ?? "not served"}${field.data?.levels?.[l.id] != null ? "%" : ""}`).join(" · ")}{field.data.here ? ` · in ${field.data.here}` : ""}</span>
              )}
              {field.error && <span className="text-signal-alert">lights · FAILED GET /field · {field.error}</span>}
              {notes}
            </div>
          </div>
          <Module title="Site map" meta="the house, a stand-in for a site" size="auto"
            className="[&>[data-slot=card-content]]:flex [&>[data-slot=card-content]]:flex-1">
            <TwinMap {...props} focus={focus}
              live={props.live && { ...props.live, decisions,
                ...(calibrating && { calibrate: (pose) => act("Calibrate", [["/dog/calibrate", pose]]).then(refresh) }),
                ...(stretching && scale.data && { stretch: (f) => {
                  setStretching(false);
                  act("Scale", [["/dog/scale", { px_per_m: Math.round(scale.data!.px_per_m * f * 2) / 2 }]]).then(refresh);
                } }) }}
              onMapClick={placing ? (xy) => {
                setPlacing(false);
                act("Place the dog", [["/dog/calibrate", { p: [Math.round(xy[0]), Math.round(xy[1])], heading_deg: d?.map?.heading_deg ?? 0 }]]).then(refresh);
              } : undefined}
              className="h-auto min-h-[820px] flex-1" />
          </Module>
        </div>
        <div className="col-span-12 flex flex-col gap-4 lg:col-span-4 lg:self-start">
          <Camera connected={!!d?.connected} />
          <Body dog={dog.data} error={dog.error} lidar={lidar.data} lidarError={lidar.error} fresh={fresh} />
        </div>
      </div>

      <Receipts rows={rows} timeZone={TZ} timeline={false} loading={!ledger.data && !ledger.error}
        marker={(r) => rowNumber.get(r)} onPoint={point}
        error={ledger.error ? `FAILED ${ledger.error}` : undefined}
        meta={shift.error ? `run · FAILED ${shift.error}` : shift.data ? `run · ${shift.data.shift_id}` : undefined} />
    </div>
  );
}

function toRow(r: ApiRow): LedgerRow {
  return {
    ts: r.ts, tool: r.tool, ok: r.ok, latency_ms: r.latency_ms, cached: r.cached, source: r.source === "stub" ? "stub" : "live",
    args: redactDeep(r.args), state_before: redactDeep(r.state_before as Record<string, unknown>), state_after: redactDeep(r.state_after as Record<string, unknown>),
    error: r.ok ? undefined : redact(String(r.response_or_error ?? "")),
  };
}

function DogChip({ dog, error, fresh }: { dog?: DogState; error?: string; fresh: boolean }) {
  if (error) return <SignalChip tone="alert">Dog · FAILED {error}</SignalChip>;
  if (!dog) return <SignalChip tone="neutral">Dog · reading</SignalChip>;
  if (!dog.connected) return <SignalChip tone="neutral">Dog off</SignalChip>;
  if (dog.state?.age_ms == null) return <SignalChip tone="alert">Dog on · no state served</SignalChip>;   // never a made-up "0 ms"
  if (!fresh) { const a = age(dog.state.age_ms); return <SignalChip tone="alert">Dog stale · {a.value} {a.unit}</SignalChip>; }
  return <SignalChip tone="good">Dog on · {dog.recheck ? "confirm its location" : dog.calibrated ? "located" : "not located"}</SignalChip>;
}

export function CastleChip({ chat, error }: { chat?: Chat; error?: string }) {
  if (error) return <SignalChip tone="alert">Group chat · FAILED {error}</SignalChip>;
  if (!chat) return <SignalChip tone="neutral">Group chat · reading</SignalChip>;
  if (!chat.alive) return <SignalChip tone="alert">{chat.group} · listener down</SignalChip>;
  return <SignalChip tone="good">{chat.group} · {chat.pending ? "waiting for who dis" : chat.armed ? "armed" : "listening"}</SignalChip>;
}

/** The body as served: connection, freshness, where it thinks it is, avoidance, the follow, the scan. */
function Body({ dog, error, lidar, lidarError, fresh, className }: {
  dog?: DogState; error?: string; lidar?: LidarPx; lidarError?: string; fresh: boolean; className?: string;
}) {
  const f = dog?.follow ?? {};
  const rows: Array<[string, React.ReactNode]> = dog ? [
    ["Connection", dog.connected ? `connected · mode ${dog.state?.mode ?? "?"}` : "not connected"],
    ["State age", dog.state?.age_ms != null ? <span className={fresh ? undefined : "text-signal-alert"}>{dog.state.age_ms} ms</span> : "none"],
    ["Thinks it is", dog.map ? `${dog.map.p.join(", ")} px · ${dog.map.heading_deg}°` : "not calibrated"],
    ["Avoidance", dog.connected ? (dog.avoid ? "on" : <span className="text-signal-alert">OFF</span>) : "not connected"],
    ["Follow", f.active
      ? `waypoint ${f.i} of ${f.n} · ${f.dist_px ?? "?"} px · ${f.err_deg ?? "?"}°${f.stopped_at != null ? ` · stopped at ${f.stopped_at}` : ""}`
      : f.error ? <span className="text-signal-alert">{redact(f.error)}</span>
      : f.done ? `done · reached ${(f.reached ?? []).join(", ")}` : "idle"],
    ["Live scan", lidarError ? <span className="text-signal-alert">FAILED {lidarError}</span>
      : lidar ? `${lidar.on ? "on" : "off"} · ${lidar.n} frames${lidar.frame?.id ? ` · ${lidar.frame.id}` : ""}${lidar.why ? ` · ${lidar.why}` : ""}` : dog.connected ? "reading" : "not connected"],
  ] : [];
  return (
    <Module title="Body" size="auto" className={className}
      error={error ? `FAILED ${error}` : undefined} loading={!dog && !error}>
      {dog?.recheck && (
        <p role="alert" className="mb-4 text-[13px] text-signal-alert">Reconnected: press Calibrate and drag the dog on the map to where it really is.</p>
      )}
      <dl className="flex flex-col gap-2 text-[13px]">
        {rows.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[104px_1fr] gap-2">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="font-mono text-[12px] leading-5">{v}</dd>
          </div>
        ))}
      </dl>
    </Module>
  );
}
