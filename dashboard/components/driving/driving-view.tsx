"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Camera } from "lucide-react";
import {
  Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { ActionButton, Module, WaitingChip } from "@/components/wtdd";
import { TwinMap } from "@/components/twin/twin-map";
import { PageHeader } from "@/components/shell/page-header";
import { useApp } from "@/components/shell/app-state";
import { LiveTag, LiveTraces, Watching, watchers, withPose } from "@/components/live/live-view";
import { StopDialog } from "@/components/live/stop-dialog";
import type { MapData } from "@/lib/data";
import { cn } from "@/lib/utils";

/** Driving the dog by hand, outside any routine. Starting asks the person to confirm first. */
export function DrivingView({ map }: { map: MapData }) {
  const { live, routines, startDriving, walkPath, takePhoto, endSession, zones, confirmZone, people } = useApp();
  const [stopping, setStopping] = useState(false);
  const [draft, setDraft] = useState<Array<[number, number]>>([]);
  const [confirm, setConfirm] = useState(false);
  const driving = live?.session.kind === "driving";
  const busy = !!live && !driving;
  const routine = routines.find((r) => r.id === live?.session.routineId);


  const makeRule = (id: string) => {
    const z = zones.find((x) => x.id === id);
    confirmZone(id);
    toast("Made it a rule", { description: z?.name.replace(/^Proposed:\s*/i, "") });
  };

  return (
    <>
      <PageHeader crumbs={[{ label: "Driving" }]} />

      <div className="flex flex-col gap-4">
        {live && (
          <div className="flex items-center gap-2">
            <LiveTag live={live} routine={routine} />
            <Watching names={watchers(people)} className="ml-auto" />
          </div>
        )}
        <div className="grid grid-cols-12 gap-4">
          <Module title="Site map" size="auto" className="col-span-12 lg:col-span-8 [&>[data-slot=card-content]]:flex [&>[data-slot=card-content]]:flex-1">
            <TwinMap
              {...map}
              zones={zones}
              devices={withPose(map.devices, live)}
              routes={driving ? pathRoutes(live!.pose.position, live!.path, draft) : []}
              stops={draft.map((p, i) => ({ id: `wp-${i}`, index: i + 1, name: `Point ${i + 1}`, position: p, look: "nod" as const }))}
              onMapClick={driving ? (xy) => setDraft((d) => [...d, [Math.round(xy[0] * 10) / 10, Math.round(xy[1] * 10) / 10]]) : undefined}
              runActive={driving}
              className="h-auto min-h-[520px] flex-1"
            />
          </Module>

          <div className="col-span-12 grid content-start gap-4 md:grid-cols-2 lg:col-span-4 lg:grid-cols-1">
            <Module title="Controls" size="auto" actions={driving ? <ActionButton intent="secondary" size="sm" onClick={() => setStopping(true)}>Stop driving</ActionButton> : undefined}>
              {driving ? (
                <div className="flex flex-col gap-3">
                  <p className="text-[15px] leading-[22px] text-muted-foreground">
                    {draft.length === 0
                      ? live!.path.length > 0 ? "Walking. Click the map to add more points." : "Click the map to lay out a path."
                      : `${draft.length} ${draft.length === 1 ? "point" : "points"}. Go when ready.`}
                  </p>
                  <div className="flex gap-2">
                    <ActionButton intent="primary" disabled={draft.length === 0} onClick={() => { walkPath(draft); setDraft([]); }}>Go</ActionButton>
                    <ActionButton intent="quiet" disabled={draft.length === 0} onClick={() => setDraft([])}>Clear</ActionButton>
                    <ActionButton intent="secondary" onClick={takePhoto} className="ml-auto"><Camera strokeWidth={1.5} />Photo</ActionButton>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col gap-3">
                  <p className="text-[15px] leading-[22px] text-muted-foreground">
                    {busy ? "A routine is running. Stop it before driving." : "The dog is parked."}
                  </p>
                  <ActionButton intent="primary" disabled={busy} onClick={() => setConfirm(true)} className="self-start">Start driving</ActionButton>
                </div>
              )}
            </Module>

            <Module title="Zones" size="auto">
              <ul className="flex flex-col">
                {zones.map((z) => (
                  <li key={z.id} className="flex flex-col gap-2 border-t border-border py-2.5 first:border-t-0 first:pt-0">
                    <span className="flex items-center gap-2">
                      <span aria-hidden className={cn("size-3 rounded-sm border", z.kind === "nogo" ? "border-signal-alert bg-signal-alert-soft" : "border-dashed border-foreground/60 bg-highlight")} />
                      <span className="text-[13px] font-medium">{z.name}</span>
                    </span>
                    {z.status === "awaiting_tap" && (
                      <span className="flex items-center gap-2">
                        <WaitingChip>Awaiting a tap</WaitingChip>
                        <ActionButton intent="person" size="sm" className="ml-auto" onClick={() => makeRule(z.id)}>Make it a rule</ActionButton>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </Module>
          </div>

          {driving && live && <LiveTraces live={live} map={map} />}
        </div>
      </div>

      <StopDialog
        open={stopping}
        onOpenChange={setStopping}
        what="driving"
        onStop={(dest) => { setDraft([]); endSession(dest); toast("Stopped driving", { description: dest ? `Heading to ${dest.name}` : "Staying where it is" }); }}
      />

      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle className="text-[17px]">Are you ready to drive the dog?</DialogTitle>
            <DialogDescription className="text-[15px] leading-[22px]">
              Check that the area around it is clear and that you can see it. Every move is logged to this session.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild><ActionButton intent="secondary">Not yet</ActionButton></DialogClose>
            <ActionButton intent="primary" onClick={() => { startDriving(); setConfirm(false); }}>Start driving</ActionButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

type XY = [number, number];

/** The path on the map: what the dog is still walking (solid), then the clicked-out draft after it. */
function pathRoutes(from: XY, walking: XY[], draft: XY[]) {
  const line = [from, ...walking, ...draft];
  if (line.length < 2) return [];
  return [{ id: "drive-path", name: "Path", source: "driving", status: "exists_on_main" as const, polyline: line }];
}
