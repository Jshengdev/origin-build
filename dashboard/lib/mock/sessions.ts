/** Mock sessions: each time the dog ran a routine or was driven, with the rows it logged. */
import ledger from "@/lib/data/fixtures/ledger-rows.json";
import type { Fixture, LedgerRow } from "@/lib/data";

export interface Session {
  id: number;
  kind: "routine" | "driving";
  routineId?: string;
  startedAt: string;
  endedAt?: string;
  rows: LedgerRow[];
}

const row = (ts: string, tool: string, extra: Partial<LedgerRow> = {}): LedgerRow =>
  ({ ts, tool, ok: true, latency_ms: 300, source: "stub", cached: true, ...extra });

export const INITIAL_SESSIONS: Session[] = [
  { id: 14, kind: "routine", routineId: "night-round", startedAt: "2026-09-26T23:00:06Z", endedAt: "2026-09-26T23:13:55Z", rows: (ledger as Fixture<LedgerRow[]>).data },
  {
    id: 13, kind: "driving", startedAt: "2026-09-25T19:10:00Z", endedAt: "2026-09-25T19:24:00Z",
    rows: [
      row("2026-09-25T19:10:00Z", "drive.start"),
      row("2026-09-25T19:12:30Z", "dog.move", { args: { dir: "forward", m: 0.5 } }),
      row("2026-09-25T19:14:00Z", "dog.look", { args: { kind: "photo" } }),
      row("2026-09-25T19:18:00Z", "dog.look", { args: { kind: "photo" } }),
      row("2026-09-25T19:24:00Z", "drive.stop"),
    ],
  },
  {
    id: 12, kind: "routine", routineId: "progress-check", startedAt: "2026-09-25T16:30:00Z", endedAt: "2026-09-25T16:36:00Z",
    rows: [
      row("2026-09-25T16:30:00Z", "routine.start", { args: { routine: "progress-check" } }),
      row("2026-09-25T16:31:10Z", "dog.look", { args: { kind: "photo" }, stop: "p1" }),
      row("2026-09-25T16:33:40Z", "dog.look", { args: { kind: "photo" }, stop: "p2" }),
      row("2026-09-25T16:35:20Z", "dog.look", { args: { kind: "photo" }, stop: "p3" }),
      row("2026-09-25T16:36:00Z", "routine.done"),
    ],
  },
];
