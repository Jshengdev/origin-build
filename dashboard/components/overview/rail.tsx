import Link from "next/link";
import { Card } from "@/components/ui/card";
import { Module, Reading, SignalChip } from "@/components/wtdd";
import { age, shortTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Device, Look, Person, Roster, Stop } from "@/lib/data";

/**
 * Display constant for the stale chip, not a served value. Confirm the real cutoff with item 24 (PR #16).
 */
const STALE_MS = 2000;

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2 px-4 first:pl-0 last:pr-0">
      <span className="text-[13px] font-medium text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}

/** Body vitals in one card: battery and the three stream ages, as served. Half width from lg up. */
export function BodyStats({ body, className }: { body?: Device; className?: string }) {
  const v = body?.vitals;
  if (!v) {
    return <p className="text-[15px] text-muted-foreground">No body state. Check that the dog is on and the API answers.</p>;
  }
  const streams = [["State", v.stateAgeMs], ["Video", v.videoAgeMs], ["Lidar", v.lidarAgeMs]] as const;
  return (
    <Card className={cn("w-full border-0 px-4 py-4 shadow-none lg:w-1/2", className)}>
      <div className="grid grid-cols-4 divide-x divide-border">
        <Stat label="Battery">
          <Reading value={v.batteryPct} unit="%" />
          {v.faults.length > 0 && (
            <div className="flex flex-wrap gap-1">{v.faults.map((f) => <SignalChip key={f} tone="alert">{f}</SignalChip>)}</div>
          )}
        </Stat>
        {streams.map(([name, ms]) => {
          const a = age(ms);
          return (
            <Stat key={name} label={name}>
              <Reading value={a.value} unit={a.unit} />
              {ms > STALE_MS && <SignalChip tone="alert" className="self-start">stale</SignalChip>}
            </Stat>
          );
        })}
      </div>
    </Card>
  );
}

export function TonightsRoster({ roster, stops, devices, people, routine, className }: {
  roster: Roster; stops: Stop[]; devices: Device[]; people: Person[]; routine?: { id: string; name: string }; className?: string;
}) {
  const onCall = people.find((p) => p.id === roster.onCall);
  return (
    <Module title="Tonight's roster" size="auto" className={className}>
      <dl className="flex flex-col gap-3 text-[13px]">
        {routine && (
          <Row label="Routine">
            <Link href={`/routines/${routine.id}`} className="font-medium underline-offset-4 hover:underline">{routine.name}</Link>
          </Row>
        )}
        <Row label="Stops">
          <ol className="flex flex-col gap-1">
            {roster.stopsToBody.map((id) => {
              const s = stops.find((x) => x.id === id);
              return (
                <li key={id} className="flex items-baseline gap-2">
                  <span className="font-mono text-[12px] text-muted-foreground">{s?.index ?? "?"}</span>
                  <span>{s?.name ?? id}</span>
                </li>
              );
            })}
          </ol>
        </Row>
        <Row label="Camera">
          {Object.entries(roster.cameraToZone).map(([cam, zone]) => (
            <div key={cam}>{devices.find((d) => d.id === cam)?.name ?? cam} <span className="text-muted-foreground">to</span> {zone}</div>
          ))}
        </Row>
        <Row label="On call">
          {onCall ? onCall.name : <span className="text-muted-foreground">Nobody on call</span>}
        </Row>
      </dl>
    </Module>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[80px_1fr] gap-2">
      <dt className="font-medium text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function LastLook({ look, stop, timeZone, className }: { look?: Look; stop?: Stop; timeZone: string; className?: string }) {
  return (
    <Module title="Last look" size="auto" className={className} meta={look ? shortTime(look.ts, timeZone) : undefined}>
      {!look ? (
        <p className="text-[15px] text-muted-foreground">No looks yet. The dog looks at each stop on its round.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={look.image} alt={`Look at ${stop?.name ?? look.stop}`} className="aspect-[16/10] w-full rounded-md border border-border object-cover" />
          <span className="text-[13px] font-medium">{stop?.name ?? look.stop}</span>
          <p className="text-[15px] leading-[22px]">{look.sentence}</p>
          {look.pins.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {look.pins.map((p, i) => <SignalChip key={i} tone="neutral">{p.label} {p.p.toFixed(2)}</SignalChip>)}
            </div>
          )}
        </div>
      )}
    </Module>
  );
}
