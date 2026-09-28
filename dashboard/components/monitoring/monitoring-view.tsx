import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Module, Reading, SignalChip } from "@/components/wtdd";
import { BodyStats } from "@/components/overview/rail";
import type { Device, Evals } from "@/lib/data";

const statusTone = { online: "good", offline: "neutral", stale: "alert", error: "alert" } as const;
const placed = (d: Device) => (d.kind === "body" ? "" : d.placedBy === "hand" ? "By hand" : d.placedBy === "click" ? "By a click" : "");
const resultTone = { pass: "good", fail: "alert", unsafe: "alert" } as const;

export function MonitoringView({ devices, evals }: { devices: Device[]; evals: Evals }) {
  const body = devices.find((d) => d.kind === "body");
  return (
    <div className="flex flex-col gap-4">
      <BodyStats body={body} />
      <div className="grid grid-cols-12 gap-4">
        <Module title="Devices" size="auto" className="col-span-12 lg:col-span-8">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-[13px] text-muted-foreground">Device</TableHead>
                <TableHead className="text-[13px] text-muted-foreground">Status</TableHead>
                <TableHead className="text-[13px] text-muted-foreground">Integration</TableHead>
                <TableHead className="text-[13px] text-muted-foreground">Placed</TableHead>
                <TableHead className="text-right text-[13px] text-muted-foreground">Light</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {devices.map((d) => (
                <TableRow key={d.id} className="h-10">
                  <TableCell className="text-[13px]">{d.name}</TableCell>
                  <TableCell><SignalChip tone={statusTone[d.status]}>{d.status}</SignalChip></TableCell>
                  <TableCell className="font-mono text-[12px] text-muted-foreground">{d.integration}</TableCell>
                  <TableCell className="text-[13px] text-muted-foreground">{placed(d)}</TableCell>
                  <TableCell className="text-right">
                    {d.kind === "light" && (d.on ? <Reading size="sm" value={d.brightness ?? 0} unit="bri" /> : <span className="font-mono text-[13px] text-muted-foreground">off</span>)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Module>

        <Module title="Evals" size="auto" className="col-span-12 lg:col-span-4">
          <ul className="flex flex-col">
            {evals.grades.map((g) => (
              <li key={g.scenario} className="flex flex-col gap-1 border-t border-border py-2.5 first:border-t-0 first:pt-0">
                <span className="flex items-center gap-2">
                  <span className="text-[13px]">{g.scenario}</span>
                  <SignalChip tone={resultTone[g.result]} className="ml-auto">{g.result}</SignalChip>
                </span>
                {g.why && <span className="text-[13px] text-muted-foreground">{g.why}</span>}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[12px] text-muted-foreground">{evals.label}</p>
        </Module>
      </div>
    </div>
  );
}
