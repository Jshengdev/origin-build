"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ActionButton, Module } from "@/components/wtdd";
import { PageHeader } from "@/components/shell/page-header";
import { useApp } from "@/components/shell/app-state";
import type { AreaImage } from "@/lib/mock/images";
import { day, dayTime } from "@/lib/format";

const newestFirst = (a: { takenAt: string }, b: { takenAt: string }) => b.takenAt.localeCompare(a.takenAt);

/** Images grouped by routine (one card per point), then standalone photos from driving. */
export function ImagesView() {
  const { routines, images, captures } = useApp();
  const router = useRouter();

  const groups = routines
    .map((r) => ({
      routine: r,
      areas: r.steps
        .map((st) => ({ step: st, shots: images.filter((im) => im.routineId === r.id && im.stepId === st.id).sort(newestFirst) }))
        .filter((a) => a.shots.length > 0),
    }))
    .filter((g) => g.areas.length > 0);

  return (
    <>
      <PageHeader crumbs={[{ label: "Images" }]} />
      <div className="flex flex-col gap-4">
        {groups.map(({ routine, areas }) => (
          <Module
            key={routine.id}
            title={routine.name}
            size="full"
            className="scroll-mt-20"
            actions={<ActionButton intent="secondary" size="sm" asChild><Link href={`/images/${routine.id}`}>Compare nights</Link></ActionButton>}
          >
            <div id={routine.id} className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
              {areas.map(({ step, shots }) => (
                <AreaCard
                  key={step.id}
                  name={step.name}
                  latest={shots[0]}
                  count={shots.length}
                  onOpen={() => router.push(`/images/${routine.id}/${step.id}`)}
                />
              ))}
            </div>
          </Module>
        ))}

        <section className="flex flex-col gap-3">
          <h2 className="text-[15px] font-semibold">From driving</h2>
          {captures.length === 0 ? (
            <Module title="From driving" size="full" className="[&>[data-slot=card-header]]:hidden">
              <p className="text-[15px] text-muted-foreground">No photos yet. Take one while driving the dog.</p>
            </Module>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
                {captures.slice(0, 4).map((c) => (
                  <Card key={c.id} className="gap-2 border-0 p-2 shadow-none">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={c.image} alt={`Photo near ${c.near}`} className="aspect-[16/10] w-full rounded-md object-cover" />
                    <div className="flex items-baseline justify-between gap-2 px-1 pb-1">
                      <span className="truncate text-[13px] font-medium">{c.near}</span>
                      <span className="shrink-0 text-[12px] text-muted-foreground">{day(c.takenAt)}</span>
                    </div>
                  </Card>
                ))}
              </div>
              <Module title="All photos" size="full">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="w-20 text-[13px] text-muted-foreground"><span className="sr-only">Photo</span></TableHead>
                      <TableHead className="text-[13px] text-muted-foreground">Near</TableHead>
                      <TableHead className="text-[13px] text-muted-foreground">Taken</TableHead>
                      <TableHead className="text-[13px] text-muted-foreground">Session</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {[...captures].sort(newestFirst).map((c) => (
                      <TableRow key={c.id} className="h-14">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <TableCell><img src={c.image} alt="" className="h-10 w-16 rounded-sm object-cover" /></TableCell>
                        <TableCell className="text-[13px]">{c.near}</TableCell>
                        <TableCell className="text-[13px] text-muted-foreground">{dayTime(c.takenAt)}</TableCell>
                        <TableCell className="text-[13px]">
                          <Link href={`/sessions/${c.sessionId}`} className="underline-offset-4 hover:underline">Session {c.sessionId}</Link>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Module>
            </>
          )}
        </section>
      </div>
    </>
  );
}

export function AreaCard({ name, latest, count, onOpen }: { name: string; latest: AreaImage; count: number; onOpen: () => void }) {
  return (
    <Card
      role="link"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => { if (e.key === "Enter") onOpen(); }}
      className="cursor-pointer gap-2 border-0 bg-background p-2 shadow-none outline-none transition-colors duration-150 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={latest.image} alt={`${name}, latest`} className="aspect-[16/10] w-full rounded-md object-cover" />
      <div className="flex items-baseline justify-between gap-2 px-1 pb-1">
        <span className="truncate text-[13px] font-medium">{name}</span>
        <span className="shrink-0 text-[12px] text-muted-foreground">{count} · {day(latest.takenAt)}</span>
      </div>
    </Card>
  );
}
