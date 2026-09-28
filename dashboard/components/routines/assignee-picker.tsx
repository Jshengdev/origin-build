"use client";
import { Bot, User } from "lucide-react";
import { Label } from "@/components/ui/label";
import { Select, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Avatar, SelectMenu } from "@/components/wtdd";
import { useApp } from "@/components/shell/app-state";
import { roleLabel } from "@/lib/mock/people";
import type { Assignee } from "@/lib/mock/routines";

/** Robot or a person. A person-assigned routine goes to their queue instead of running the dog. */
export function AssigneePicker({ value, onChange }: { value: Assignee; onChange: (a: Assignee) => void }) {
  const { people } = useApp();
  return (
    <div className="flex flex-col gap-2">
      <Label className="text-[13px] font-medium">Assigned to</Label>
      <ToggleGroup
        type="single"
        variant="outline"
        value={value.kind}
        onValueChange={(k) => k && onChange(k === "robot" ? { kind: "robot" } : { kind: "person", personId: value.kind === "person" ? value.personId : people[0]?.id })}
        className="w-full"
      >
        <ToggleGroupItem value="robot" className="flex-1 gap-1.5 text-[13px]"><Bot className="size-4" strokeWidth={1.5} />Robot</ToggleGroupItem>
        <ToggleGroupItem value="person" className="flex-1 gap-1.5 text-[13px]"><User className="size-4" strokeWidth={1.5} />Person</ToggleGroupItem>
      </ToggleGroup>
      {value.kind === "person" && (
        <Select value={value.personId} onValueChange={(id) => onChange({ kind: "person", personId: id })}>
          <SelectTrigger aria-label="Person" className="h-9 w-full border-input bg-card text-[13px] shadow-none">
            <SelectValue />
          </SelectTrigger>
          <SelectMenu>
            {people.map((p) => (
              <SelectItem key={p.id} value={p.id} className="text-[13px]">
                <span className="flex items-center gap-2"><Avatar name={p.name} size={20} />{p.name}<span className="text-muted-foreground">{roleLabel(p.role)}</span></span>
              </SelectItem>
            ))}
          </SelectMenu>
        </Select>
      )}
    </div>
  );
}

/** "Robot" or the person's avatar and name. */
export function AssigneeLabel({ value }: { value: Assignee }) {
  const { people } = useApp();
  if (value.kind === "robot") return <span className="flex items-center gap-1.5 text-[13px] text-muted-foreground"><Bot className="size-4" strokeWidth={1.5} />Robot</span>;
  const p = people.find((x) => x.id === value.personId);
  return <span className="flex items-center gap-1.5 text-[13px] text-muted-foreground"><Avatar name={p?.name ?? "?"} size={20} />{p?.name ?? "Someone"}</span>;
}
