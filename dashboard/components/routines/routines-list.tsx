"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Card } from "@/components/ui/card";
import { ActionButton, SignalChip, LiveMark } from "@/components/wtdd";
import { TwinMap } from "@/components/twin/twin-map";
import { PageHeader } from "@/components/shell/page-header";
import { useApp } from "@/components/shell/app-state";
import { routineAsRoute, stepsAsStops } from "@/lib/mock/routine-map";
import { AssigneeLabel } from "./assignee-picker";
import type { MapData } from "@/lib/data";
import { day } from "@/lib/format";

export function RoutinesList({ map }: { map: MapData }) {
  const { routines, live } = useApp();
  const router = useRouter();
  return (
    <>
      <PageHeader crumbs={[{ label: "Routines" }]} />
      <div className="flex flex-col gap-4">
      <ActionButton intent="primary" asChild className="self-start">
        <Link href="/routines/new"><Plus strokeWidth={1.5} />New routine</Link>
      </ActionButton>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {routines.map((r) => {
          const open = () => router.push(`/routines/${r.id}`);
          const running = live?.session.routineId === r.id;
          return (
            <Card
              key={r.id}
              role="link"
              tabIndex={0}
              onClick={open}
              onKeyDown={(e) => { if (e.key === "Enter") open(); }}
              className="cursor-pointer gap-3 border-0 p-3 shadow-none outline-none transition-colors duration-150 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
            >
              {/* A picture of the route; not interactive inside the card. */}
              <div inert>
                <TwinMap
                  grid={map.grid}
                  floorPlan={map.floorPlan}
                  zones={map.zones}
                  stops={stepsAsStops(r.steps)}
                  routes={routineAsRoute(r)}
                  compact
                  className="h-44"
                />
              </div>
              <div className="flex items-center gap-2 px-1">
                <span className="text-[15px] font-medium">{r.name}</span>
                {running && <SignalChip tone="good" mark={<LiveMark />}>Running</SignalChip>}
              </div>
              <div className="flex items-center gap-3 px-1 pb-1 text-[13px] text-muted-foreground">
                <span>{r.steps.length} {r.steps.length === 1 ? "point" : "points"}</span>
                {r.lastRun && <span>Last run {day(r.lastRun)}</span>}
                <span className="ml-auto"><AssigneeLabel value={r.assignee} /></span>
              </div>
            </Card>
          );
        })}
      </div>
      </div>
    </>
  );
}
