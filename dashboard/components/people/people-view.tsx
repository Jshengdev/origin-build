"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ActionButton, Avatar, Module, SelectMenu, WaitingChip } from "@/components/wtdd";
import { PageActions, PageHeader } from "@/components/shell/page-header";
import { useApp } from "@/components/shell/app-state";
import { CHANNELS, GROUP, ROLES, type Channel, type Role } from "@/lib/mock/people";

export function PeopleView() {
  const { people, setRole, addPerson, waiting, me } = useApp();
  const [adding, setAdding] = useState(false);

  return (
    <>
      <PageHeader crumbs={[{ label: "People" }]} />
      <div className="flex flex-col gap-4">
        <PageActions>
          <ActionButton intent="primary" onClick={() => setAdding(true)}><Plus strokeWidth={1.5} />Add person</ActionButton>
        </PageActions>

        <div className="grid grid-cols-12 gap-4">
          <Module title="People" size="auto" className="col-span-12 lg:col-span-8">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="text-[13px] text-muted-foreground">Name</TableHead>
                  <TableHead className="text-[13px] text-muted-foreground">Role</TableHead>
                  <TableHead className="text-[13px] text-muted-foreground">Reached by</TableHead>
                  <TableHead className="text-[13px] text-muted-foreground">Quiet hours</TableHead>
                  <TableHead className="text-[13px] text-muted-foreground">Waiting</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {people.map((p) => {
                  const open = waiting.filter((w) => w.personId === p.id).length;
                  return (
                    <TableRow key={p.id} className="h-12 hover:bg-transparent">
                      <TableCell>
                        <span className="flex items-center gap-2 text-[13px] font-medium">
                          <Avatar name={p.name} size={28} />{p.name}
                          {p.id === me && <span className="font-normal text-muted-foreground">(you)</span>}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Select value={p.role} onValueChange={(r) => { setRole(p.id, r as Role); toast(`${p.name} is now ${ROLES.find((x) => x.value === r)?.label}`); }}>
                          <SelectTrigger aria-label={`${p.name} role`} className="h-8 w-[140px] border-input bg-card text-[13px] shadow-none"><SelectValue /></SelectTrigger>
                          <SelectMenu>{ROLES.map((r) => <SelectItem key={r.value} value={r.value} className="text-[13px]">{r.label}</SelectItem>)}</SelectMenu>
                        </Select>
                      </TableCell>
                      <TableCell className="text-[13px]">{CHANNELS[p.channel]}</TableCell>
                      <TableCell className="text-[13px] text-muted-foreground">{p.quietHours ?? "None"}</TableCell>
                      <TableCell>{open > 0 ? <WaitingChip>{open} waiting</WaitingChip> : <span className="text-[13px] text-muted-foreground">Nothing</span>}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </Module>

          <div className="col-span-12 flex flex-col gap-4 lg:col-span-4">
            <Module title="Roles" size="auto">
              <dl className="flex flex-col gap-2.5">
                {ROLES.map((r) => (
                  <div key={r.value} className="grid grid-cols-[72px_1fr] gap-2 text-[13px]">
                    <dt className="font-medium">{r.label}</dt>
                    <dd className="text-muted-foreground">{r.can}</dd>
                  </div>
                ))}
              </dl>
            </Module>
            <Module title="Group" size="auto">
              <span className="flex items-center gap-2 text-[13px]">
                <Avatar name="The Castle" size={28} />
                <span className="flex flex-col"><span className="font-medium">{GROUP.name}</span><span className="text-muted-foreground">{CHANNELS[GROUP.channel]}, where rounds start</span></span>
              </span>
            </Module>
          </div>
        </div>
      </div>

      <AddPerson open={adding} onOpenChange={setAdding} onAdd={(p) => { addPerson(p); toast(`Added ${p.name}`); }} />
    </>
  );
}

function AddPerson({ open, onOpenChange, onAdd }: {
  open: boolean; onOpenChange: (o: boolean) => void; onAdd: (p: { name: string; role: Role; channel: Channel }) => void;
}) {
  const [name, setName] = useState("");
  const [role, setRoleValue] = useState<Role>("viewer");
  const [channel, setChannel] = useState<Channel>("sms");
  const ok = name.trim().length > 1;
  const submit = () => { if (!ok) return; onAdd({ name: name.trim(), role, channel }); setName(""); onOpenChange(false); };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader><DialogTitle className="text-[17px]">Add a person</DialogTitle></DialogHeader>
        <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <div className="flex flex-col gap-2">
            <Label htmlFor="person-name" className="text-[13px] font-medium">Name</Label>
            <Input id="person-name" autoFocus value={name} onChange={(e) => setName(e.target.value)} className="border-input bg-card shadow-none" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-2">
              <Label className="text-[13px] font-medium">Role</Label>
              <Select value={role} onValueChange={(v) => setRoleValue(v as Role)}>
                <SelectTrigger aria-label="Role" className="h-9 w-full border-input bg-card text-[13px] shadow-none"><SelectValue /></SelectTrigger>
                <SelectMenu>{ROLES.map((r) => <SelectItem key={r.value} value={r.value} className="text-[13px]">{r.label}</SelectItem>)}</SelectMenu>
              </Select>
            </div>
            <div className="flex flex-col gap-2">
              <Label className="text-[13px] font-medium">Reached by</Label>
              <Select value={channel} onValueChange={(v) => setChannel(v as Channel)}>
                <SelectTrigger aria-label="Reached by" className="h-9 w-full border-input bg-card text-[13px] shadow-none"><SelectValue /></SelectTrigger>
                <SelectMenu>
                  <SelectItem value="sms" className="text-[13px]">SMS</SelectItem>
                  <SelectItem value="imessage_1to1" className="text-[13px]">iMessage</SelectItem>
                </SelectMenu>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <DialogClose asChild><ActionButton intent="secondary" type="button">Cancel</ActionButton></DialogClose>
            <ActionButton intent="primary" type="submit" disabled={!ok}>Add person</ActionButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
