"use client";
import { useState, useSyncExternalStore } from "react";
import { useTheme } from "next-themes";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Module, SignalChip } from "@/components/wtdd";
import type { Integration, Site } from "@/lib/data";


export function SettingsView({ site, integrations }: { site: Site; integrations: Integration[] }) {
  const [mode, setMode] = useState(site.mode);
  const [noPlan, setNoPlan] = useState(site.noPlan);
  const { theme, setTheme } = useTheme();
  // The theme is only known on the client; render no selection on the server.
  const mounted = useSyncExternalStore(() => () => {}, () => true, () => false);

  return (
    <div className="mx-auto flex w-full max-w-[720px] flex-col gap-4">
      <Module title="Site" size="full">
        <div className="flex flex-col gap-4">
          <Field label="Name" htmlFor="site-name">
            <Input id="site-name" defaultValue={site.name.replace(/\s*\(stand-in for a site\)/i, "")} className="border-input bg-card shadow-none" />
          </Field>
          <Field label="Mode">
            <ToggleGroup type="single" value={mode} onValueChange={(v) => v && setMode(v as Site["mode"])} variant="outline">
              <ToggleGroupItem value="house" className="px-3 text-[13px]">House</ToggleGroupItem>
              <ToggleGroupItem value="site" className="px-3 text-[13px]">Site</ToggleGroupItem>
            </ToggleGroup>
          </Field>
          <label className="flex items-center justify-between gap-4">
            <span className="flex flex-col">
              <span className="text-[13px] font-medium">No floor plan</span>
              <span className="text-[13px] text-muted-foreground">Use only the map the dog drew.</span>
            </span>
            <Switch checked={noPlan} onCheckedChange={setNoPlan} />
          </label>
        </div>
      </Module>

      <Module title="Integrations" size="full">
        <ul className="flex flex-col">
          {integrations.map((i) => (
            <li key={i.id} className="flex items-center gap-4 border-t border-border py-2.5 first:border-t-0 first:pt-0">
              <span className="text-[13px]">{i.what}</span>
              {/^EXISTS/.test(i.status)
                ? <SignalChip tone="good" className="ml-auto">connected</SignalChip>
                : <SignalChip tone="neutral" className="ml-auto">not connected</SignalChip>}
            </li>
          ))}
        </ul>
      </Module>

      <Module title="Appearance" size="full">
        <Field label="Theme">
          <ToggleGroup type="single" value={mounted ? theme : undefined} onValueChange={(v) => v && setTheme(v)} variant="outline">
            <ToggleGroupItem value="light" className="px-3 text-[13px]">Light</ToggleGroupItem>
            <ToggleGroupItem value="dark" className="px-3 text-[13px]">Dark</ToggleGroupItem>
            <ToggleGroupItem value="system" className="px-3 text-[13px]">System</ToggleGroupItem>
          </ToggleGroup>
        </Field>
      </Module>
    </div>
  );
}

function Field({ label, htmlFor, children }: { label: string; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={htmlFor} className="text-[13px] font-medium">{label}</Label>
      {children}
    </div>
  );
}
