"use client";
import { useState } from "react";
import { Select, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card } from "@/components/ui/card";
import { Module, SignalChip, SelectMenu } from "@/components/wtdd";
import { PageHeader } from "@/components/shell/page-header";
import { Notes } from "./notes";
import { useApp } from "@/components/shell/app-state";
import { dayTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/** One point of a routine: every image by date, and two dates side by side for a progress check. */
export function AreaView({ routineId, stepId }: { routineId: string; stepId: string }) {
  const { routines, images } = useApp();
  const routine = routines.find((r) => r.id === routineId);
  const step = routine?.steps.find((s) => s.id === stepId);
  const shots = images.filter((im) => im.routineId === routineId && im.stepId === stepId).sort((a, b) => b.takenAt.localeCompare(a.takenAt));

  const [before, setBefore] = useState<string | undefined>(shots[shots.length - 1]?.id);
  const [after, setAfter] = useState<string | undefined>(shots[0]?.id);
  const A = shots.find((s) => s.id === before);
  const B = shots.find((s) => s.id === after);

  const crumbs = [
    { label: "Images", href: "/images" },
    { label: routine?.name ?? "Routine", href: routine ? `/images/${routine.id}` : undefined },
    { label: step?.name ?? "Point" },
  ];

  if (!step || shots.length === 0) {
    return (
      <>
        <PageHeader crumbs={crumbs} />
        <Module title="Images" size="full"><p className="text-[15px] text-muted-foreground">No images here yet. They appear after the routine runs.</p></Module>
      </>
    );
  }

  /** Clicking a picture puts it on the side it belongs: earlier than "After" goes to Before, otherwise After. */
  const pick = (id: string) => {
    const shot = shots.find((s) => s.id === id)!;
    if (B && shot.takenAt < B.takenAt) setBefore(id);
    else setAfter(id);
  };

  return (
    <>
      <PageHeader crumbs={crumbs} />
      <div className="flex flex-col gap-4">
        <Module title="Compare" size="full">
          <p className="mb-3 text-[13px] text-muted-foreground">Drag a picture from below onto either side, or pick a date.</p>
          <div className="grid gap-4 md:grid-cols-2">
            <Side label="Before" value={before} onChange={setBefore} shots={shots} shot={A} />
            <Side label="After" value={after} onChange={setAfter} shots={shots} shot={B} />
          </div>
        </Module>

        <Notes routineId={routineId} stepId={stepId} />

        <Module title="All images" size="full" meta={`${shots.length}`}>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
            {shots.map((s) => {
              const tag = s.id === before ? "Before" : s.id === after ? "After" : null;
              return (
                <Card
                  key={s.id}
                  role="button"
                  tabIndex={0}
                  aria-pressed={!!tag}
                  onClick={() => pick(s.id)}
                  draggable
                  onDragStart={(e) => { e.dataTransfer.setData(DRAG_TYPE, s.id); e.dataTransfer.effectAllowed = "copy"; }}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(s.id); } }}
                  className={cn(
                    "relative cursor-grab gap-1.5 active:cursor-grabbing border-0 bg-background p-1.5 shadow-none outline-none transition-colors duration-150 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
                    tag && "bg-accent",
                  )}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={s.image} alt={`${step.name}, ${dayTime(s.takenAt)}`} draggable={false} className="aspect-[16/10] w-full rounded-sm object-cover" />
                  <span className="px-0.5 text-[12px] text-muted-foreground">{dayTime(s.takenAt)}</span>
                  {tag && <SignalChip tone="neutral" className="absolute left-3 top-3 bg-card">{tag}</SignalChip>}
                </Card>
              );
            })}
          </div>
        </Module>
      </div>
    </>
  );
}

const DRAG_TYPE = "application/x-wtdd-image";

function Side({ label, value, onChange, shots, shot }: {
  label: string; value?: string; onChange: (v: string) => void; shots: Array<{ id: string; takenAt: string }>; shot?: { image: string; takenAt: string };
}) {
  const [over, setOver] = useState(false);
  return (
    <div
      className={cn("flex flex-col gap-2 rounded-md p-2 -m-2 transition-colors duration-150", over && "bg-accent ring-2 ring-ring")}
      onDragOver={(e) => { if (e.dataTransfer.types.includes(DRAG_TYPE)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setOver(true); } }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOver(false); }}
      onDrop={(e) => { e.preventDefault(); setOver(false); const id = e.dataTransfer.getData(DRAG_TYPE); if (id) onChange(id); }}
    >
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-medium">{label}</span>
        <Select value={value} onValueChange={onChange}>
          <SelectTrigger aria-label={`${label} date`} className="ml-auto h-8 w-[200px] border-input bg-card text-[13px] shadow-none">
            <SelectValue placeholder="Pick a date" />
          </SelectTrigger>
          <SelectMenu>
            {shots.map((s) => <SelectItem key={s.id} value={s.id} className="text-[13px]">{dayTime(s.takenAt)}</SelectItem>)}
          </SelectMenu>
        </Select>
      </div>
      {shot
        // eslint-disable-next-line @next/next/no-img-element
        ? <img src={shot.image} alt={`${label}: ${dayTime(shot.takenAt)}`} draggable={false} className="pointer-events-none aspect-[16/10] w-full rounded-md object-cover" />
        : <div className="aspect-[16/10] w-full rounded-md bg-accent" />}
    </div>
  );
}
