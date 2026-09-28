"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Pencil } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ActionButton, Module } from "@/components/wtdd";
import { TwinMap } from "@/components/twin/twin-map";
import { PageActions, PageHeader } from "@/components/shell/page-header";
import { useApp } from "@/components/shell/app-state";
import { routineAsRoute, stepsAsStops } from "@/lib/mock/routine-map";
import { actionLabel, type Assignee, type Routine } from "@/lib/mock/routines";
import { AssigneeLabel, AssigneePicker } from "./assignee-picker";
import type { MapData } from "@/lib/data";
import { dayTime } from "@/lib/format";
import { PointsList, useStepsDraft } from "./routine-editor";

export function RoutineDetail({ id, map }: { id: string; map: MapData }) {
  const { routines } = useApp();
  const r = routines.find((x) => x.id === id);

  if (!r) {
    return (
      <>
        <PageHeader crumbs={[{ label: "Routines", href: "/routines" }, { label: "Not found" }]} />
        <Module title="Routine" size="full"><p className="text-[15px] text-muted-foreground">No routine with that name. It may have been made in another tab.</p></Module>
      </>
    );
  }
  // Keyed by id so edit state resets when moving between routines.
  return <RoutinePage key={r.id} routine={r} map={map} />;
}

function RoutinePage({ routine: r, map }: { routine: Routine; map: MapData }) {
  const { live, startRoutine, updateRoutine, sendRoutine, waiting, people } = useApp();
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(r.name);
  const [assignee, setAssignee] = useState<Assignee>(r.assignee);
  const person = r.assignee.kind === "person" ? people.find((p) => p.id === (r.assignee as { personId: string }).personId) : undefined;
  const sent = waiting.some((w) => w.routineId === r.id);
  const draft = useStepsDraft(r.steps);

  const run = () => { startRoutine(r.id); router.push("/live"); };
  const edit = () => { setName(r.name); setAssignee(r.assignee); draft.setSteps(r.steps); draft.setSelected(null); setEditing(true); };
  const canSave = name.trim().length > 0 && draft.steps.length > 0;
  const save = () => {
    if (!canSave) return;
    updateRoutine(r.id, { name: name.trim(), steps: draft.steps, assignee });
    setEditing(false);
    toast("Routine saved", { description: name.trim() });
  };

  const steps = editing ? draft.steps : r.steps;

  return (
    <>
      <PageHeader crumbs={[{ label: "Routines", href: "/routines" }, { label: editing ? name || r.name : r.name }]} />
      <div className="flex flex-col gap-4">
        <PageActions>
          {editing ? (
            <>
              <ActionButton intent="primary" disabled={!canSave} onClick={save}>Save</ActionButton>
              <ActionButton intent="quiet" onClick={() => setEditing(false)}>Cancel</ActionButton>
            </>
          ) : (
            <>
              {person ? (
                <ActionButton intent="primary" disabled={sent} onClick={() => { sendRoutine(r.id); toast(`Sent to ${person.name}`); }}>
                  {sent ? `Waiting on ${person.name}` : `Send to ${person.name}`}
                </ActionButton>
              ) : (
                <ActionButton intent="primary" disabled={!!live} onClick={run}>Run routine</ActionButton>
              )}
              <ActionButton intent="secondary" onClick={edit}><Pencil strokeWidth={1.5} />Edit</ActionButton>
              <ActionButton intent="secondary" asChild><Link href={`/images/${r.id}`}>Images</Link></ActionButton>
            </>
          )}
        </PageActions>

        <div className="grid grid-cols-12 gap-4">
          <Module title="Route" size="auto" className="col-span-12 lg:col-span-8 [&>[data-slot=card-content]]:flex [&>[data-slot=card-content]]:flex-1">
            <TwinMap
              {...map}
              stops={stepsAsStops(steps)}
              routes={routineAsRoute({ id: r.id, name: r.name, steps })}
              looks={[]}
              selectedStopIds={editing && draft.selected ? [draft.selected] : []}
              onMapClick={editing ? draft.add : undefined}
              onStopClick={editing ? draft.setSelected : undefined}
              className="h-auto min-h-[520px] flex-1"
            />
          </Module>

          <div className="col-span-12 flex flex-col gap-4 lg:col-span-4">
            {editing ? (
              <>
                <Module title="Routine" size="auto">
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="routine-name" className="text-[13px] font-medium">Name</Label>
                    <Input id="routine-name" value={name} onChange={(e) => setName(e.target.value)} className="border-input bg-card shadow-none" />
                  </div>
                  <div className="mt-4"><AssigneePicker value={assignee} onChange={setAssignee} /></div>
                </Module>
                <PointsList draft={draft} />
              </>
            ) : (
              <Module title="Steps" size="auto" actions={<AssigneeLabel value={r.assignee} />}>
                {r.lastRun && <p className="-mt-2 mb-3 text-[13px] text-muted-foreground">Last run {dayTime(r.lastRun)}</p>}
                <ol className="flex flex-col">
                  {r.steps.map((st, i) => (
                    <li key={st.id} className="grid grid-cols-[28px_1fr] items-center gap-3 border-t border-border py-2.5 first:border-t-0 first:pt-0">
                      <span className="flex size-6 items-center justify-center rounded-full bg-accent text-[12px] font-medium">{i + 1}</span>
                      <span className="flex flex-col">
                        <span className="text-[13px] font-medium">{st.name}</span>
                        <span className="text-[13px] text-muted-foreground">{actionLabel(st.action)}</span>
                      </span>
                    </li>
                  ))}
                </ol>
              </Module>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
