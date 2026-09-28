"use client";
/**
 * Settings' Monitoring on the live API (Johnny: "let's get monitoring live and put that into settings"): every integration
 * the system leans on, from GET /integrations (#72: unitree, lidar, hue, tuya, imessage, jev, openrouter, ledger), and the
 * dog's own state from GET /dog/state. Each shows what the API served: ok, FAILED with its detail, or unknown (null: never
 * connected, switched off, no row), and when that evidence is from. A key is shown as set or not, never the key. Nothing
 * here connects the dog or calls a service; a failed read is FAILED, never a mock value (no battery: the API serves none).
 */
import { Module, SignalChip } from "@/components/wtdd";
import { redact, usePoll, type DogState, type IntegrationsJson } from "@/lib/data/api";
import { age, clock } from "@/lib/format";

const WHAT: Record<string, string> = {
  unitree: "The dog (Unitree Go2)", lidar: "LiDAR", hue: "Hue lights", tuya: "Tuya LED strip", imessage: "The group chat (iMessage)",
  jev: "Jev (vision)", openrouter: "OpenRouter (the model)", ledger: "The ledger",
};

export function MonitoringLive() {
  const ints = usePoll<IntegrationsJson>("/integrations", 5000);
  const dog = usePoll<DogState>("/dog/state", 2000);
  const d = dog.data;
  const rows: Array<[string, string]> = d ? [
    ["Connection", d.connected ? "connected" : "not connected"],
    ["State age", d.state?.age_ms != null ? (({ value, unit }) => `${value} ${unit}`)(age(d.state.age_ms)) : "none"],
    ["Located", d.calibrated ? "yes" : "not calibrated"],
    ["Avoidance", d.avoid == null ? "not connected" : d.avoid ? "on" : "off"],
  ] : [];
  return (
    <div className="grid grid-cols-12 gap-4">
      <Module title="Monitoring" meta={ints.data ? `checked ${clock(ints.data.checked_at)}` : undefined} size="auto" className="col-span-12 lg:col-span-8"
        loading={!ints.data && !ints.error} error={ints.error ? `FAILED GET /integrations · ${redact(ints.error)}` : undefined}>
        <ul className="flex flex-col">
          {(ints.data?.integrations ?? []).map((i) => (
            <li key={i.name} className="grid grid-cols-[minmax(0,14rem)_auto_minmax(0,1fr)_auto] items-center gap-3 border-t border-border py-2.5 first:border-t-0 first:pt-0">
              <span className="text-[13px]">{WHAT[i.name] ?? i.name}</span>
              {i.ok === true ? <SignalChip tone="good">ok</SignalChip> : i.ok === false ? <SignalChip tone="alert">FAILED</SignalChip> : <SignalChip tone="neutral">unknown</SignalChip>}
              <span className="truncate font-mono text-[12px] text-muted-foreground" title={redact(i.detail)}>
                {redact(i.detail)}{i.key_set != null && ` · key ${i.key_set ? "set" : "not set"}`}
              </span>
              <span className="font-mono text-[12px] text-muted-foreground">{i.as_of ? clock(i.as_of) : "no evidence"}</span>
            </li>
          ))}
        </ul>
      </Module>
      <Module title="The dog" size="auto" className="col-span-12 lg:col-span-4"
        loading={!d && !dog.error} error={dog.error ? `FAILED GET /dog/state · ${redact(dog.error)}` : undefined}>
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-[13px]">
          {rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted-foreground">{k}</dt><dd className="font-mono">{v}</dd></div>)}
        </dl>
      </Module>
    </div>
  );
}
