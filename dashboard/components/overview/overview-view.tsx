import Link from "next/link";
import { ActionButton, Module } from "@/components/wtdd";
import { rowDetail } from "@/components/live/ledger";
import { clock } from "@/lib/format";
import type { Device, LedgerRow, Look, Person, Roster, Site, Stop } from "@/lib/data";
import { BodyStats, LastLook, TonightsRoster } from "./rail";
import { INITIAL_ROUTINES } from "@/lib/mock/routines";

export interface OverviewData {
  site: Site; stops: Stop[]; devices: Device[]; people: Person[]; roster: Roster; ledger: LedgerRow[]; looks: Look[];
}

/** The night at a glance: body, tonight's plan, the last look, and the latest rows. */
export function OverviewView(d: OverviewData) {
  const body = d.devices.find((x) => x.kind === "body");
  const lastLook = [...d.looks].sort((a, b) => b.ts.localeCompare(a.ts))[0];
  const tz = d.site.timezone;
  /** Tonight's routine: the one whose points are the roster's stops, in order. */
  const routine = INITIAL_ROUTINES.find((r) => r.steps.map((s) => s.id).join() === d.roster.stopsToBody.join());

  return (
    <div className="flex flex-col gap-4">
      <BodyStats body={body} />
      <div className="grid grid-cols-12 gap-4">
        <TonightsRoster roster={d.roster} stops={d.stops} devices={d.devices} people={d.people} routine={routine} className="col-span-12 md:col-span-6 lg:col-span-4" />
        <LastLook look={lastLook} stop={d.stops.find((s) => s.id === lastLook?.stop)} timeZone={tz} className="col-span-12 md:col-span-6 lg:col-span-4" />
        <Module
          title="Latest"
          size="auto"
          className="col-span-12 lg:col-span-4"
          actions={<ActionButton intent="primary" size="sm" asChild><Link href="/live">Open Live</Link></ActionButton>}
        >
          <ol className="flex flex-col">
            {d.ledger.map((r) => (
              <li key={`${r.ts}-${r.tool}`} className="grid grid-cols-[64px_1fr] gap-x-3 border-t border-border py-2 first:border-t-0 first:pt-0">
                <span className="font-mono text-[12px] leading-5 text-muted-foreground">{clock(r.ts, tz)}</span>
                <span className="flex min-w-0 items-baseline gap-2">
                  {!r.ok && <span aria-label="failed" className="text-[10px] text-signal-alert">●</span>}
                  <span className="font-mono text-[13px]">{r.tool}</span>
                </span>
                <span />
                <span className={`truncate text-[13px] ${r.ok ? "text-muted-foreground" : "text-signal-alert"}`}>{rowDetail(r)}</span>
              </li>
            ))}
          </ol>
        </Module>
      </div>
    </div>
  );
}
