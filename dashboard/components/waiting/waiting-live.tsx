"use client";
/**
 * Waiting on the live API (V4 of the live-feature map, rows W1 and W2): each ask the dog put to the group, and the answer
 * that decided it. Both come from GET /ledger rows; there is no route of their own.
 *   the ask: a chat.post the dog sent as kind "escalate", or any post whose trigger a reply names (args.asked);
 *   the answers: every intruder.verdict naming that trigger, in time order (listen.py writes one per hold and one more
 *   when the ask is handled or expires); the last is the outcome. S10's by and say, 17's meaning and p (state_after).
 * Replies come from THE CASTLE; the page never answers for the group. Every string is redacted (S10); a stand-in row
 * (cached, or source stub) says so. The page computes nothing: acked_ms is written in seconds, as served.
 */
import { createContext, useContext } from "react";
import { Avatar, Module, SignalChip, WaitingChip } from "@/components/wtdd";
import { PageActions } from "@/components/shell/page-header";
import { CastleChip } from "@/components/overview/overview-live";
import { age, clock } from "@/lib/format";
import { redact, usePoll, type ApiRow, type Chat } from "@/lib/data/api";

const TZ = "America/Los_Angeles";
type Obj = Record<string, unknown>;
const str = (v: unknown) => (typeof v === "string" ? v : undefined);
const num = (v: unknown) => (typeof v === "number" ? v : undefined);
const standIn = (r: ApiRow) => r.cached === true || r.source === "stub";

/** The asks and every verdict, from one GET /ledger read: Waiting's list, and the sidebar's count (openAsks). */
function useLedgerAsks() {
  const ledger = usePoll<ApiRow[]>("/ledger?n=500", 3000);
  const rows = ledger.data ?? [];
  const verdicts = rows.filter((r) => r.tool === "intruder.verdict");
  const answered = new Set(verdicts.map((v) => str((v.args as Obj | undefined)?.asked)).filter(Boolean));
  const asks = rows.filter((r) => {
    const a = (r.args ?? {}) as Obj;
    return r.tool === "chat.post" && (a.kind === "escalate" || answered.has(str(a.trigger)));
  }).reverse();   // newest first
  return { ledger, verdicts, answered, asks };
}

const Asks = createContext<ReturnType<typeof useLedgerAsks> | null>(null);
/** In the app shell: one GET /ledger?n=500 every 3 s for the sidebar and Waiting both, not one poll each. */
export function AsksProvider({ children }: { children: React.ReactNode }) {
  return <Asks.Provider value={useLedgerAsks()}>{children}</Asks.Provider>;
}
export function useAsks() {
  const v = useContext(Asks);
  if (!v) throw new Error("useAsks needs <AsksProvider> (components/shell/app-shell.tsx)");
  return v;
}

/**
 * The asks Waiting shows as "Waiting for an answer" (sent, no verdict names them yet), without the stand-ins: the shell's
 * yellow count never carries a fixture unbadged. Undefined until the ledger is read or when the read failed: the count is
 * absent then, never a 0 standing in for an error, and the sidebar shows FAILED in its place.
 */
export function openAsks({ ledger, answered, asks }: ReturnType<typeof useLedgerAsks>) {
  if (!ledger.data) return undefined;
  return asks.filter((r) => r.ok && !standIn(r) && !answered.has(str((r.args as Obj | undefined)?.trigger))).length;
}

export function WaitingLive() {
  const chat = usePoll<Chat>("/chat", 3000);
  const { ledger, verdicts, asks } = useAsks();

  return (
    <div className="flex flex-col gap-4">
      <PageActions>
        <CastleChip chat={chat.data} error={chat.error} />
        <span className="text-[13px] text-muted-foreground">Replies come from the group chat; the first clear answer decides.</span>
      </PageActions>
      {ledger.error ? (
        <Module title="Waiting" size="full" error={`FAILED ${ledger.error}`} />
      ) : asks.length === 0 ? (
        <Module title="Waiting" size="full" className="py-12 text-center [&>[data-slot=card-header]]:hidden" loading={!ledger.data}>
          <p className="text-[15px] text-muted-foreground">Nothing is waiting. When the dog is not sure, it asks the group, and the ask shows here.</p>
        </Module>
      ) : (
        <div className="flex flex-col gap-4">
          {asks.map((ask) => {
            const trigger = str((ask.args as Obj | undefined)?.trigger);
            const answers = verdicts.filter((v) => str((v.args as Obj | undefined)?.asked) === trigger);   // oldest first
            return <Ask key={`${ask.ts}-${trigger}`} ask={ask} answers={answers} group={chat.data?.group} />;
          })}
        </div>
      )}
    </div>
  );
}

/** The mockup's card: a short title with the group and time, one chip row when there is a chip, the ask as the body sentence. */
function Ask({ ask, answers, group }: { ask: ApiRow; answers: ApiRow[]; group?: string }) {
  const a = (ask.args ?? {}) as Obj;
  const text = str(a.text);
  const waiting = ask.ok && !answers.length;
  return (
    <Module title="Question from the dog" size="full" meta={`${group ?? "the group"} · ${clock(ask.ts, TZ)}`}>
      <div className="flex flex-col gap-2">
        {(standIn(ask) || !ask.ok || waiting) && (
          <span className="flex flex-wrap items-center gap-2">
            {standIn(ask) && <SignalChip tone="neutral">stand-in</SignalChip>}
            {!ask.ok && <SignalChip tone="alert">FAILED</SignalChip>}
            {waiting && <WaitingChip>Waiting for an answer</WaitingChip>}
          </span>
        )}
        <p className="text-[15px] leading-[22px]">{text ? redact(text) : "The dog asked"}</p>
        {!ask.ok && <p role="alert" className="font-mono text-[12px] text-signal-alert">{redact(String(ask.response_or_error ?? ""))}</p>}
        {answers.length > 0 && <Answers rows={answers} />}
      </div>
    </Module>
  );
}

/**
 * The conversation as it happened: every intruder.verdict for this ask, oldest first, one block each. An acked_ms row is
 * "answered after N s", a closed_ms row "closed after N s" (N the served milliseconds written in seconds). The last row
 * is marked as the outcome when there is more than one.
 */
function Answers({ rows }: { rows: ApiRow[] }) {
  return (
    <div className="flex flex-col gap-2">
      {rows.map((r, i) => <Answer key={`${r.ts}-${i}`} row={r} outcome={rows.length > 1 && i === rows.length - 1} />)}
    </div>
  );
}

function Answer({ row, outcome }: { row: ApiRow; outcome?: boolean }) {
  const a = (row.args ?? {}) as Obj, s = (row.state_after ?? {}) as Obj;
  const by = redact(str(a.by) ?? "a member");
  const acked = num(a.acked_ms), closed = num(a.closed_ms);
  const secs = (ms: number) => { const t = age(ms); return `${t.value} ${t.unit}`; };
  const when = acked != null ? `answered after ${secs(acked)}` : closed != null ? `closed after ${secs(closed)}` : String(s.verdict ?? "answered");
  const meaning = str(s.meaning), p = num(s.p);
  return (
    <div className="flex items-start gap-2 rounded-md border border-border bg-background p-4">
      <Avatar name={by} size={28} />
      <div className="flex min-w-0 flex-col gap-1">
        <span className="text-[13px] font-medium">
          {outcome && <span className="text-muted-foreground">Outcome · </span>}{by} {when}
          {standIn(row) && <span className="font-normal text-muted-foreground"> · stand-in</span>}
        </span>
        {str(a.say) ? <p className="text-[15px] leading-[22px]">{redact(str(a.say)!)}</p>
          : str(a.text) && <p className="text-[15px] leading-[22px]">“{redact(str(a.text)!)}”</p>}
        {(meaning || s.verdict != null) && (
          <span className="font-mono text-[12px] text-muted-foreground">
            {meaning ? `read as ${meaning}${p != null ? ` · p ${p.toFixed(2)}` : ""}` : `verdict ${String(s.verdict)}`}{str(s.action) ? ` · ${str(s.action)}` : ""}
          </span>
        )}
        {str(a.acked_error) && <span role="alert" className="font-mono text-[12px] text-signal-alert">no reply clock: {redact(str(a.acked_error)!)}</span>}
      </div>
    </div>
  );
}
