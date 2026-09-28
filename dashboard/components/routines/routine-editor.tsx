"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ActionButton, Module, SelectMenu } from "@/components/wtdd";
import { TwinMap } from "@/components/twin/twin-map";
import { PageActions, PageHeader } from "@/components/shell/page-header";
import { useApp } from "@/components/shell/app-state";
import { routineAsRoute, stepsAsStops } from "@/lib/mock/routine-map";
import { ACTIONS, type Action, type Assignee, type RoutineStep } from "@/lib/mock/routines";
import { AssigneePicker } from "./assignee-picker";
import type { MapData } from "@/lib/data";
import { cn } from "@/lib/utils";

/** Points being edited: add by clicking the map, rename, change the action, remove. Shared by new and edit. */
export function useStepsDraft(initial: RoutineStep[] = []) {
  const [steps, setSteps] = useState<RoutineStep[]>(initial);
  const [selected, setSelected] = useState<string | null>(null);
  const add = (position: [number, number]) => {
    const id = `pt-${Date.now().toString(36)}`;
    setSteps((s) => [...s, { id, name: `Point ${s.length + 1}`, position: [Math.round(position[0] * 10) / 10, Math.round(position[1] * 10) / 10], action: "photo" }]);
    setSelected(id);
  };
  const update = (id: string, patch: Partial<RoutineStep>) => setSteps((s) => s.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  const remove = (id: string) => setSteps((s) => s.filter((x) => x.id !== id));
  return { steps, setSteps, selected, setSelected, add, update, remove };
}
export type StepsDraft = ReturnType<typeof useStepsDraft>;

/** New routine: click the map to drop points, then pick what the dog does at each one. */
export function RoutineEditor({ map }: { map: MapData }) {
  const { addRoutine } = useApp();
  const router = useRouter();
  const [name, setName] = useState("");
  const [assignee, setAssignee] = useState<Assignee>({ kind: "robot" });
  const draft = useStepsDraft();
  const { steps, selected, setSelected, add } = draft;

  const canSave = name.trim().length > 0 && steps.length > 0;
  const save = () => {
    if (!canSave) return;
    const r = addRoutine({ name: name.trim(), steps, assignee });
    toast("Routine saved", { description: r.name });
    router.push(`/routines/${r.id}`);
  };

  return (
    <>
      <PageHeader crumbs={[{ label: "Routines", href: "/routines" }, { label: "New routine" }]} />
      <div className="flex flex-col gap-4">
      <PageActions>
        <ActionButton intent="primary" disabled={!canSave} onClick={save}>Save routine</ActionButton>
        <ActionButton intent="quiet" asChild><Link href="/routines">Cancel</Link></ActionButton>
      </PageActions>
      <div className="grid grid-cols-12 gap-4">
        <Module title="Map" size="auto" className="col-span-12 lg:col-span-8 [&>[data-slot=card-content]]:flex [&>[data-slot=card-content]]:flex-1">
          <TwinMap
            {...map}
            routes={routineAsRoute({ id: "draft", name, steps })}
            stops={stepsAsStops(steps)}
            looks={[]}
            selectedStopIds={selected ? [selected] : []}
            onMapClick={add}
            onStopClick={setSelected}
            className="h-auto min-h-[560px] flex-1"
          />
        </Module>

        <div className="col-span-12 flex flex-col gap-4 lg:col-span-4">
          <Module title="Routine" size="auto">
            <div className="flex flex-col gap-2">
              <Label htmlFor="routine-name" className="text-[13px] font-medium">Name</Label>
              <Input id="routine-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Progress check" className="border-input bg-card shadow-none" />
            </div>
            <div className="mt-4"><AssigneePicker value={assignee} onChange={setAssignee} /></div>
          </Module>

          <PointsList draft={draft} />
        </div>
      </div>
      </div>
    </>
  );
}

export function PointsList({ draft }: { draft: StepsDraft }) {
  const { steps, selected, setSelected, update, remove } = draft;
  return (
    <Module title="Points" size="auto">
      {steps.length === 0 ? (
        <p className="text-[15px] text-muted-foreground">Click the map to add a point.</p>
      ) : (
        <ol className="flex flex-col gap-1">
          {steps.map((st, i) => (
            <li
              key={st.id}
              onClick={() => setSelected(st.id)}
              className={cn("grid grid-cols-[24px_1fr_auto] items-start gap-2 rounded-md p-2", selected === st.id && "bg-accent")}
            >
              <span className="mt-1.5 flex size-6 items-center justify-center rounded-full bg-accent text-[12px] font-medium">{i + 1}</span>
              <span className="flex flex-col gap-2">
                <Input
                  aria-label={`Point ${i + 1} name`}
                  value={st.name}
                  onChange={(e) => update(st.id, { name: e.target.value })}
                  className="h-8 border-input bg-card text-[13px] shadow-none"
                />
                <Select value={st.action} onValueChange={(v) => update(st.id, { action: v as Action })}>
                  <SelectTrigger aria-label={`Point ${i + 1} action`} className="h-8 w-full border-input bg-card text-[13px] shadow-none">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectMenu>
                    {ACTIONS.map((a) => <SelectItem key={a.value} value={a.value} className="text-[13px]">{a.label}</SelectItem>)}
                  </SelectMenu>
                </Select>
              </span>
              <ActionButton intent="quiet" size="icon" className="mt-0.5 size-8" aria-label={`Remove point ${i + 1}`} onClick={(e) => { e.stopPropagation(); remove(st.id); }}>
                <X strokeWidth={1.5} />
              </ActionButton>
            </li>
          ))}
        </ol>
      )}
    </Module>
  );
}
