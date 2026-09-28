"use client";
import Link from "next/link";
import { ActionButton, AvatarStack, Module, SignalChip, LiveMark } from "@/components/wtdd";
import { TwinMap } from "@/components/twin/twin-map";
import { PageActions, PageHeader } from "@/components/shell/page-header";
import { useApp, type Live } from "@/components/shell/app-state";
import { routineAsRoute, stepsAsStops } from "@/lib/mock/routine-map";
import type { Routine } from "@/lib/mock/routines";
import type { Device, MapData } from "@/lib/data";
import { dayTime } from "@/lib/format";
import { Receipts } from "./receipts";
import { StopDialog } from "./stop-dialog";
import { useState } from "react";
import { toast } from "sonner";
import { ME } from "@/lib/mock/people";

/** The body pin at the live pose. */
export function withPose(devices: Device[], live: Live | null): Device[] {
  if (!live) return devices;
  return devices.map((d) => (d.kind === "body" ? { ...d, position: live.pose.position, headingDeg: live.pose.headingDeg } : d));
}

/** "Live · Session 15 · Night round" */
export function LiveTag({ live, routine }: { live: Live; routine?: Routine }) {
  return (
    <span className="flex items-center gap-2">
      <SignalChip tone="good" mark={<LiveMark />}>Live</SignalChip>
      <SignalChip tone="neutral">Session {live.session.id}</SignalChip>
      <SignalChip tone="neutral">{routine ? routine.name : "Driving"}</SignalChip>
    </span>
  );
}

/** Traces as they come in, newest first. The same block sits under Driving. */
export function LiveTraces({ live, map }: { live: Live; map: MapData }) {
  return <Receipts title="Traces" rows={[...live.session.rows].reverse()} map={map} timeZone="America/Los_Angeles" />;
}

export function LiveView({ map }: { map: MapData }) {
  const { live, routines, sessions, endSession, people } = useApp();
  const [stopping, setStopping] = useState(false);
  const routine = routines.find((r) => r.id === live?.session.routineId);

  if (!live) {
    const last = sessions[0];
    const lastRoutine = routines.find((r) => r.id === last?.routineId);
    return (
      <>
        <PageHeader crumbs={[{ label: "Live" }]} />
        <Module title="Live" size="full" className="items-center py-16 text-center [&>[data-slot=card-header]]:hidden">
          <div className="flex flex-col items-center gap-4">
            <p className="text-[22px] font-semibold leading-7 tracking-[-0.01em]">Dog is not live right now.</p>
            <div className="flex gap-2">
              <ActionButton intent="secondary" asChild><Link href="/routines">Run a routine</Link></ActionButton>
              <ActionButton intent="primary" asChild><Link href="/driving">Drive the dog</Link></ActionButton>
            </div>
            {last && (
              <Link href={`/sessions/${last.id}`} className="text-[13px] text-muted-foreground underline-offset-4 hover:underline">
                Last session: {last.id} · {lastRoutine?.name ?? "Driving"} · {dayTime(last.startedAt)}
              </Link>
            )}
          </div>
        </Module>
      </>
    );
  }

  return (
    <>
      <PageHeader crumbs={routine ? [{ label: "Live" }, { label: routine.name }] : [{ label: "Live" }]} />
      <div className="flex flex-col gap-4">
        <PageActions>
          <LiveTag live={live} routine={routine} />
          <Watching names={watchers(people)} className="ml-auto" />
          <ActionButton intent="secondary" onClick={() => setStopping(true)}>{routine ? "Stop routine" : "Stop driving"}</ActionButton>
        </PageActions>
        <StopDialog
          open={stopping}
          onOpenChange={setStopping}
          what={routine ? "routine" : "driving"}
          onStop={(dest) => { endSession(dest); toast(routine ? "Routine stopped" : "Stopped driving", { description: dest ? `Heading to ${dest.name}` : "Staying where it is" }); }}
        />
        <div className="grid grid-cols-12 gap-4">
          <Module title="Where it is" size="full">
            <TwinMap
              {...map}
              devices={withPose(map.devices, live)}
              stops={routine ? stepsAsStops(routine.steps) : []}
              routes={routine ? routineAsRoute(routine) : []}
              looks={[]}
              runActive
              className="h-[420px]"
            />
          </Module>
          <LiveTraces live={live} map={map} />
        </div>
      </div>
    </>
  );
}

/** Who has Live open. Mock: you, plus whoever is on call and driving. */
export function watchers(people: Array<{ id: string; name: string; role: string }>) {
  const me = people.find((p) => p.id === ME);
  const others = people.filter((p) => p.id !== ME && (p.role === "on_call" || p.role === "driver"));
  return [me, ...others].filter(Boolean).map((p) => p!.name);
}

export function Watching({ names, className }: { names: string[]; className?: string }) {
  return (
    <span className={`flex items-center gap-2 text-[13px] text-muted-foreground ${className ?? ""}`} title={names.join(", ")}>
      <AvatarStack names={names} size={24} />
      {names.length} watching
    </span>
  );
}
