"use client";
/**
 * Routines on the live API (#71, wtdd/routines.py): each demo route kept by name and put back on the map in one tap
 * (Johnny's Loom, beat 3: "kitchen to bedroom 2" and "bedroom 2 to living room"). A routine is the map's path, stops and
 * actions; GET /routines lists them and names the one on the map now (`loaded`).
 *   Load     POST /routines {action: "load", name}: the API writes the routine's route into the map and answers with that
 *            map. The page holds the answered map until the poll serves it (never its _version alone, which would keep
 *            the old route drawn and let a later save write it back: docs/api-contract.md). Refused while a walk runs (409).
 *   Run      Load, then walk it with the checkpoint look (components/live/walk-route.tsx): a look at each stop, a post
 *            only where the stop says so; no stops, a straight POST /dog/follow. Needs the dog calibrated.
 *   Save as  POST /routines {action: "save", name}: the map's route now, under a name; a name already saved is replaced.
 *   Stops    the shared Stops card (components/live/stops-card.tsx), as on Paths, edits the route on the map; "Save changes
 *            to <name>" re-saves the routine being edited (the loaded one, else the last this page loaded: an edit makes the
 *            map's route differ, so GET /routines' `loaded` is null until it is saved again). Save as routine and This run's
 *            looks are the shared ones too (save-as-routine.tsx, looks-album.tsx). The map is a 2D drawing (mode plan2d).
 * The list and "on the map" are what GET /routines serves after each answer, never an optimistic change; a refusal is the
 * page's FAILED line with the API's reason. Stop is always here, as on every page a walk starts from.
 */
import { useState } from "react";
import { ActionButton, Module, SignalChip } from "@/components/wtdd";
import { PageActions } from "@/components/shell/page-header";
import { TwinMap } from "@/components/twin/twin-map";
import { useLiveMap } from "@/components/twin/use-live-map";
import { post, redact, usePoll, type MapJson, type RoutinesJson } from "@/lib/data/api";
import { StopsCard } from "@/components/live/stops-card";
import { SaveAsRoutine } from "@/components/live/save-as-routine";
import { LooksAlbum } from "@/components/live/looks-album";
import { Results, useStop } from "@/components/live/stop";
import { useWalkRoute, WalkProgress } from "@/components/live/walk-route";

type Result = { what: string; ok: boolean; error?: string } | null;

export function RoutinesLive() {
  const [kick, setKick] = useState(0);
  const list = usePoll<RoutinesJson>("/routines", 3000, kick);
  const [saved, setSaved] = useState<MapJson | null>(null);   // the map a load answered with, drawn until the poll serves it
  const { dog, walking, props, map, served, notes, field, refresh } = useLiveMap(null, false, saved);
  const { stopped, button: stopButton } = useStop();
  const [result, setResult] = useState<Result>(null);
  const [busy, setBusy] = useState(false);
  // the routine being edited: the one on the map (GET /routines loaded), else the last one this page loaded, since an edit
  // to its stops makes the map's route differ from the saved one and `loaded` goes null until it is saved again
  const [lastLoaded, setLastLoaded] = useState<string | null>(null);
  const d = dog.data;

  const routines = async (body: { action: "save" | "load"; name: string }) => {
    const r = await post("/routines", body);
    if (r.ok && r.map) setSaved(r.map as MapJson);
    setKick((k) => k + 1);   // the list and "on the map" read back now, refused or not
    refresh();
    return r;
  };
  const walkRoute = useWalkRoute(field.data, setResult, setSaved);
  const load = async (n: string, walk: boolean) => {
    const what = `${walk ? "Run" : "Load"} · ${n}`;
    if (walk) {   // load, then walk it with the look at each stop
      await walkRoute.start(what, null, async () => { const r = await routines({ action: "load", name: n }); if (r.ok) setLastLoaded(n); return { ok: r.ok, error: r.error, map: r.map as MapJson | undefined }; });
      return;
    }
    setBusy(true);
    const r = await routines({ action: "load", name: n });
    setBusy(false);
    setResult(r.ok ? { what, ok: true } : { what, ok: false, error: r.error });
    if (r.ok) setLastLoaded(n);
  };
  const editing = list.data?.loaded ?? lastLoaded;
  const saveChanges = async () => {   // the loaded routine re-saved under its own name, with the stops' actions as they are now
    if (!editing) return;
    setBusy(true);
    const r = await routines({ action: "save", name: editing });
    setBusy(false);
    setResult(r.ok ? { what: `Save changes to ${editing}`, ok: true } : { what: `Save changes to ${editing}`, ok: false, error: r.error });
  };
  const rs = list.data?.routines ?? [];
  const runWhy = dog.error ? "The dog's state did not load" : !d?.calibrated ? "Calibrate on Overview first: place or drag the dog" : walking ? "Walking" : undefined;
  return (
    <div className="flex flex-col gap-4">
      <PageActions>
        {dog.error && <SignalChip tone="alert">Dog · FAILED {redact(dog.error)}</SignalChip>}
        <WalkProgress field={field.data} follow={dog.data?.follow ?? {}} stops={served?.stops ?? []} />
        <span className="ml-auto flex items-center gap-2"><span className="text-[12px] text-muted-foreground">Run looks and photographs at each stop · Stop between stops, not mid-look</span>{stopButton}</span>
      </PageActions>

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 flex flex-col gap-4 lg:col-span-5">
          {/* Results sit in this column, never above the map, as on Paths */}
          {[...stopped, result].some(Boolean) && <div className="flex flex-col gap-1"><Results rows={[...stopped, result]} />{walkRoute.lightsOff}</div>}
          <Module title="Routines" meta={list.data ? `${rs.length} saved` : undefined} size="auto"
            loading={!list.data && !list.error} error={list.error ? `FAILED GET /routines · ${redact(list.error)}` : undefined}>
            {rs.length === 0 ? (
              <p className="text-[13px] text-muted-foreground">No routine saved yet. Draw the route on Paths, then save it below by name.</p>
            ) : (
              <ul className="flex flex-col">
                {rs.map((r) => (
                  <li key={r.name} className="flex items-center gap-3 border-t border-border py-3 first:border-t-0 first:pt-0">
                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="truncate text-[14px] font-medium" title={r.name}>{r.name}</span>
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[12px] text-muted-foreground">
                        <span className="whitespace-nowrap" title={`saved ${r.saved_at.replace("T", " ")}`}>{r.dots} dots · {r.stops.length} {r.stops.length === 1 ? "stop" : "stops"} · saved {r.saved_at.slice(11, 16)}</span>
                        {list.data?.loaded === r.name && <SignalChip tone="neutral">On the map</SignalChip>}
                      </span>
                    </div>
                    <ActionButton intent="secondary" size="sm" disabled={busy || walking} title={walking ? "Walking" : "POST /routines load: put this route on the map"}
                      onClick={() => load(r.name, false)}>Load</ActionButton>
                    <ActionButton intent="primary" size="sm" disabled={busy || walkRoute.starting || !!runWhy} title={runWhy ?? "Load it, then walk it: a look and a photo at each stop"}
                      onClick={() => load(r.name, true)}>Run</ActionButton>
                  </li>
                ))}
              </ul>
            )}
          </Module>
          <StopsCard served={served} error={map.error ? `FAILED ${redact(map.error)}` : undefined} loading={!map.data && !map.error} empty="The route on the map has no stops. Add them on Paths (Stops), then save."
            onResult={setResult} onSaved={(m) => { setSaved(m); setKick((k) => k + 1); }}   // re-read "loaded" now: the edit makes the route differ
            footer={editing && (
              <ActionButton intent="secondary" size="sm" className="mt-3" disabled={busy || list.data?.loaded === editing}
                title={list.data?.loaded === editing ? "No changes: the map's route is this routine as saved" : `POST /routines save: keep these stops' actions in ${editing}`}
                onClick={saveChanges}>Save changes to {editing}</ActionButton>
            )} />
          <SaveAsRoutine served={served} loaded={list.data?.loaded} onResult={setResult}
            after={(r) => { if (r.ok && r.map) setSaved(r.map as MapJson); setKick((k) => k + 1); refresh(); }} />
          <div className="flex flex-col gap-0.5 font-mono text-[11px] text-muted-foreground empty:hidden">{notes}</div>
        </div>

        <Module title="Site map" meta="the route on the map now" size="auto"
          className="col-span-12 lg:col-span-7 [&>[data-slot=card-content]]:flex [&>[data-slot=card-content]]:flex-1">
          <TwinMap {...props} mode="plan2d" className="h-auto min-h-[720px] flex-1" />
        </Module>
      </div>

      <LooksAlbum />
    </div>
  );
}
