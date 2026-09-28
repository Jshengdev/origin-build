"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Select, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ActionButton, Module, SelectMenu } from "@/components/wtdd";
import { PageActions, PageHeader } from "@/components/shell/page-header";
import { useApp } from "@/components/shell/app-state";
import type { AreaImage } from "@/lib/mock/images";
import { cn } from "@/lib/utils";
import { AreaCard } from "./images-view";

const TZ = "America/Los_Angeles";
/** The night an image belongs to, in the site's timezone: "2026-09-26". */
const nightOf = (ts: string) => new Date(ts).toLocaleDateString("en-CA", { timeZone: TZ });
const nightLabel = (n: string) => new Date(`${n}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", weekday: "short" });

/** One routine's images: the whole batch on two nights side by side, then a card per point. */
export function RoutineImages({ routineId }: { routineId: string }) {
  const { routines, images } = useApp();
  const router = useRouter();
  const routine = routines.find((r) => r.id === routineId);
  const mine = images.filter((im) => im.routineId === routineId);
  const nights = [...new Set(mine.map((im) => nightOf(im.takenAt)))].sort().reverse();

  const [before, setBefore] = useState(nights[nights.length - 1]);
  const [after, setAfter] = useState(nights[0]);

  const crumbs = [{ label: "Images", href: "/images" }, { label: routine?.name ?? "Routine" }];
  if (!routine || mine.length === 0) {
    return (
      <>
        <PageHeader crumbs={crumbs} />
        <Module title="Images" size="full"><p className="text-[15px] text-muted-foreground">No images for this routine yet. They appear after it runs.</p></Module>
      </>
    );
  }

  /** The latest image of a point on a night, if the dog took one. */
  const shotOn = (stepId: string, night?: string): AreaImage | undefined =>
    mine.filter((im) => im.stepId === stepId && nightOf(im.takenAt) === night).sort((a, b) => b.takenAt.localeCompare(a.takenAt))[0];

  const points = routine.steps
    .map((st) => ({ step: st, shots: mine.filter((im) => im.stepId === st.id).sort((a, b) => b.takenAt.localeCompare(a.takenAt)) }))
    .filter((p) => p.shots.length > 0);

  return (
    <>
      <PageHeader crumbs={crumbs} />
      <div className="flex flex-col gap-4">
        <PageActions>
          <NightPicker label="Before" value={before} onChange={setBefore} nights={nights} />
          <NightPicker label="After" value={after} onChange={setAfter} nights={nights} />
          <ActionButton intent="secondary" asChild className="ml-auto"><Link href={`/routines/${routine.id}`}>Routine</Link></ActionButton>
        </PageActions>

        <Module title="Compare nights" size="full" meta={before && after ? `${nightLabel(before)} → ${nightLabel(after)}` : undefined}>
          <div className="flex flex-col">
            {routine.steps.map((st, i) => {
              const a = shotOn(st.id, before), b = shotOn(st.id, after);
              return (
                <div key={st.id} className="grid grid-cols-1 gap-3 border-t border-border py-4 first:border-t-0 first:pt-0 md:grid-cols-[160px_1fr_1fr]">
                  <Link href={`/images/${routine.id}/${st.id}`} className="flex items-start gap-2 text-[13px] font-medium underline-offset-4 hover:underline">
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent text-[12px]">{i + 1}</span>
                    <span className="pt-0.5">{st.name}</span>
                  </Link>
                  <Shot shot={a} label={before ? nightLabel(before) : ""} />
                  <Shot shot={b} label={after ? nightLabel(after) : ""} />
                </div>
              );
            })}
          </div>
        </Module>

        <Module title="Points" size="full">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
            {points.map(({ step, shots }) => (
              <AreaCard key={step.id} name={step.name} latest={shots[0]} count={shots.length} onOpen={() => router.push(`/images/${routine.id}/${step.id}`)} />
            ))}
          </div>
        </Module>
      </div>
    </>
  );
}

function NightPicker({ label, value, onChange, nights }: { label: string; value?: string; onChange: (v: string) => void; nights: string[] }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[13px] font-medium text-muted-foreground">{label}</span>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger aria-label={`${label} night`} className="h-8 w-[150px] border-input bg-card text-[13px] shadow-none">
          <SelectValue />
        </SelectTrigger>
        <SelectMenu>
          {nights.map((n) => <SelectItem key={n} value={n} className="text-[13px]">{nightLabel(n)}</SelectItem>)}
        </SelectMenu>
      </Select>
    </div>
  );
}

function Shot({ shot, label }: { shot?: AreaImage; label: string }) {
  return (
    <figure className="flex flex-col gap-1.5">
      {shot
        // eslint-disable-next-line @next/next/no-img-element
        ? <img src={shot.image} alt={label} className="aspect-[16/10] w-full rounded-md object-cover" />
        : <div className={cn("flex aspect-[16/10] w-full items-center justify-center rounded-md bg-accent text-[13px] text-muted-foreground")}>No image this night</div>}
      <figcaption className="text-[12px] text-muted-foreground">{label}</figcaption>
    </figure>
  );
}
