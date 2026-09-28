"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ActionButton, Module, SignalChip, LiveMark } from "@/components/wtdd";
import { PageHeader } from "@/components/shell/page-header";
import { useApp } from "@/components/shell/app-state";
import { Receipts } from "@/components/live/receipts";
import type { MapData } from "@/lib/data";
import { dayTime, duration } from "@/lib/format";

export function SessionsView() {
  const { sessions, routines, live } = useApp();
  const router = useRouter();
  const what = (routineId?: string) => routines.find((r) => r.id === routineId)?.name ?? "Driving";

  return (
    <>
      <PageHeader crumbs={[{ label: "Sessions" }]} />
      <div className="grid grid-cols-12 gap-4">
        <Module title="Sessions" size="full">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-24 text-[13px] text-muted-foreground">Session</TableHead>
                <TableHead className="text-[13px] text-muted-foreground">What</TableHead>
                <TableHead className="text-[13px] text-muted-foreground">Started</TableHead>
                <TableHead className="text-[13px] text-muted-foreground">Length</TableHead>
                <TableHead className="text-[13px] text-muted-foreground">Rows</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {live && (
                <TableRow className="h-10 cursor-pointer" onClick={() => router.push("/live")}>
                  <TableCell className="font-mono text-[13px]">{live.session.id}</TableCell>
                  <TableCell className="text-[13px]"><span className="flex items-center gap-2">{what(live.session.routineId)}<SignalChip tone="good" mark={<LiveMark />}>Live</SignalChip></span></TableCell>
                  <TableCell className="text-[13px] text-muted-foreground">{dayTime(live.session.startedAt)}</TableCell>
                  <TableCell />
                  <TableCell className="font-mono text-[13px]">{live.session.rows.length}</TableCell>
                </TableRow>
              )}
              {sessions.map((s) => (
                <TableRow
                  key={s.id}
                  tabIndex={0}
                  className="h-10 cursor-pointer outline-none focus-visible:bg-accent"
                  onClick={() => router.push(`/sessions/${s.id}`)}
                  onKeyDown={(e) => { if (e.key === "Enter") router.push(`/sessions/${s.id}`); }}
                >
                  <TableCell className="font-mono text-[13px]">{s.id}</TableCell>
                  <TableCell className="text-[13px]">{what(s.routineId)}</TableCell>
                  <TableCell className="text-[13px] text-muted-foreground">{dayTime(s.startedAt)}</TableCell>
                  <TableCell className="font-mono text-[13px]">{s.endedAt ? duration(s.startedAt, s.endedAt) : ""}</TableCell>
                  <TableCell className="font-mono text-[13px]">{s.rows.length}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Module>
      </div>
    </>
  );
}

export function SessionDetail({ id, map }: { id: number; map: MapData }) {
  const { sessions, routines } = useApp();
  const s = sessions.find((x) => x.id === id);
  const routine = routines.find((r) => r.id === s?.routineId);

  if (!s) {
    return (
      <>
        <PageHeader crumbs={[{ label: "Sessions", href: "/sessions" }, { label: `Session ${id}` }]} />
        <Module title="Session" size="full"><p className="text-[15px] text-muted-foreground">No session {id}. If it is running, it is on Live.</p></Module>
      </>
    );
  }

  return (
    <>
      <PageHeader crumbs={[{ label: "Sessions", href: "/sessions" }, { label: `Session ${s.id}` }]} />
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          {routine
            ? <ActionButton intent="secondary" size="sm" asChild><Link href={`/routines/${routine.id}`}>{routine.name}</Link></ActionButton>
            : <SignalChip tone="neutral">Driving</SignalChip>}
          <SignalChip tone="neutral">{dayTime(s.startedAt)}</SignalChip>
          {s.endedAt && <SignalChip tone="neutral">{duration(s.startedAt, s.endedAt)}</SignalChip>}
        </div>
        <div className="grid grid-cols-12 gap-4">
          <Receipts title="Traces" rows={[...s.rows].reverse()} map={map} timeZone="America/Los_Angeles" />
        </div>
      </div>
    </>
  );
}
