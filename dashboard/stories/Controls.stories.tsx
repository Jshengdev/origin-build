import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { useState } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ActionButton, SignalChip } from "@/components/wtdd";
import { fx } from "./fixtures";

/**
 * Stock shadcn/ui components, themed only by globals.css. Never edited; brand behavior lives in components/wtdd.
 */
const meta: Meta = { title: "Primitives/Stock controls" };
export default meta;
type Story = StoryObj;

export const DataTable: Story = {
  render: () => (
    <div className="max-w-[900px] rounded-xl bg-card p-4">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {["Device", "Status", "Integration", "Placed", "Battery"].map((h, i) => (
              <TableHead key={h} className={`text-[13px] text-muted-foreground ${i === 4 ? "text-right" : ""}`}>{h}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {fx.devices.map((d) => (
            <TableRow key={d.id} className="h-10">
              <TableCell className="text-[13px]">{d.name}</TableCell>
              <TableCell><SignalChip tone={d.status === "online" ? "good" : "alert"}>{d.status}</SignalChip></TableCell>
              <TableCell className="font-mono text-[12px]">{d.integration}</TableCell>
              <TableCell className="text-[13px] text-muted-foreground">{d.placedBy === "hand" ? "by hand" : d.placedBy === "click" ? "by a click" : "body"}</TableCell>
              <TableCell className="text-right font-mono text-[13px]">{d.vitals ? `${d.vitals.batteryPct} %` : ""}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
          </div>
  ),
};

export const Drawer: Story = {
  render: () => (
    <Sheet>
      <SheetTrigger asChild><ActionButton intent="secondary">Open a ledger row</ActionButton></SheetTrigger>
      <SheetContent side="right" className="w-[440px] gap-0 rounded-l-xl sm:max-w-[440px]">
        <SheetHeader className="gap-2 border-b border-border p-4">
          <div className="flex items-center gap-2">
            <SheetTitle className="font-mono text-[15px] font-medium">dog.look</SheetTitle>
            <SignalChip tone="alert">FAILED</SignalChip>
          </div>
          <SheetDescription className="font-mono text-[12px]">16:03:40 · 1500 ms · stop s4</SheetDescription>
        </SheetHeader>
        <div className="p-4">
          <p className="font-mono text-[13px] text-signal-alert">follower timeout at waypoint 13 (30 s)</p>
        </div>
      </SheetContent>
    </Sheet>
  ),
};

function Toggles() {
  const [on, setOn] = useState(true);
  return (
    <div className="flex max-w-[640px] flex-col gap-8">
      <label className="flex items-center gap-3 text-[13px] font-medium">
        <Switch checked={on} onCheckedChange={setOn} /> Show the occupancy grid
      </label>
      <div className="flex flex-col gap-2">
        <span className="text-[13px] font-medium text-muted-foreground">Mode</span>
        <ToggleGroup type="single" defaultValue="house" variant="outline">
          <ToggleGroupItem value="house" className="px-3 text-[13px]">House</ToggleGroupItem>
          <ToggleGroupItem value="site" className="px-3 text-[13px]">Site</ToggleGroupItem>
        </ToggleGroup>
      </div>
      <Tabs defaultValue="zones">
        <TabsList>
          <TabsTrigger value="zones" className="text-[13px]">Zones</TabsTrigger>
          <TabsTrigger value="routes" className="text-[13px]">Routes</TabsTrigger>
        </TabsList>
        <TabsContent value="zones" className="pt-2 text-[15px]">It flags; you draw. Nothing is refused on a proposal.</TabsContent>
        <TabsContent value="routes" className="pt-2 text-[15px]">Taught route, recorded by driving once.</TabsContent>
      </Tabs>
      <div className="flex flex-col gap-2">
        <Label htmlFor="site-name" className="text-[13px]">Site name</Label>
        <Input id="site-name" defaultValue={fx.site.name} className="max-w-[320px] border-input bg-card shadow-none" />
      </div>
      <Tooltip>
        <TooltipTrigger asChild><ActionButton intent="secondary" className="self-start">Reset view</ActionButton></TooltipTrigger>
        <TooltipContent>Fit the whole site</TooltipContent>
      </Tooltip>
    </div>
  );
}

export const FormAndToggles: Story = { name: "Switch, toggle group, tabs, input, tooltip", render: () => <Toggles /> };
