"use client";
/**
 * Record on the live API (V3 of the live-feature map, rows E3 and G1 to G3; the third wow, Johnny's headline): a morning
 * or night run, that run's record, the report, and one signature.
 *   GET /shift, POST /shift {name}          the run in force; "Start morning run" / "Start night run" (S11)
 *   GET /record/shifts, GET /record?shift=  the runs that exist, and one run's record (item 10's JSON, S13's route)
 *   POST /tools/record_sign {by, shift_id}  sign it once; a second signature is refused, and the refusal is shown as served
 *   GET /evals                              evals.json as written by `python -m wtdd.evals --write`, with its own time:
 *                                           the page never says it graded this run (G3)
 * The record is filmed: every string in it is redacted (flags[].to and resolved.by are raw handles). A record whose rows
 * are cached or stub says so in one line, with the served counts. Every number is the API's.
 */
import { useState } from "react";
import { Input } from "@/components/ui/input";                                              // stock shadcn
import { Select, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";     // stock shadcn
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ActionButton, Module, SelectMenu, SignalChip, WaitingChip } from "@/components/wtdd";
import { PageActions } from "@/components/shell/page-header";
import { Results, type Result } from "@/components/live/stop";
import { age, clock } from "@/lib/format";
import { post, redact, redactDeep, usePoll, type Evals, type RecordJson, type Shift, type Shifts } from "@/lib/data/api";

const TZ = "America/Los_Angeles";
const secs = (ms: number | null | undefined) => { if (ms == null) return null; const t = age(ms); return `${t.value} ${t.unit}`; };
/** A row's time; with its MM-DD before it when the record's window crosses midnight (a night run does). */
const when = (ts: string, twoDays: boolean) => (twoDays ? `${ts.slice(5, 10)} ${clock(ts, TZ)}` : clock(ts, TZ));

export function RecordLive() {
  const run = usePoll<Shift>("/shift", 5000);
  const shifts = usePoll<Shifts>("/record/shifts", 5000);
  const [picked, setPicked] = useState<string | null>(null);
  // The run in force is today's date by default even when no row is stamped with it, so it is shown only when it is one
  // of the served runs; otherwise "No run yet" (no /record read, no false 404). A 404 for a listed run stays FAILED.
  const listed = shifts.data?.shifts ?? [];
  const shiftId = picked ?? (shifts.data && listed.includes(shifts.data.current) ? shifts.data.current : null);
  const rec = usePoll<RecordJson>(shiftId ? `/record?shift=${encodeURIComponent(shiftId)}` : null, 4000);
  const evals = usePoll<Evals>("/evals", 10000);
  const [result, setResult] = useState<Result>(null);
  const [busy, setBusy] = useState(false);
  const [by, setBy] = useState(() => (typeof window === "undefined" ? "" : localStorage.getItem("wtdd.scout.by") ?? ""));

  const start = async (name: "morning" | "night") => {
    setBusy(true);
    const r = await post("/shift", { name });
    setBusy(false);
    setResult({ what: `Start ${name} run${r.ok && typeof r.shift_id === "string" ? ` · ${r.shift_id}` : ""}`, ok: r.ok, error: r.error });
    if (r.ok) setPicked(null);   // follow the run in force
  };
  const [tried, setTried] = useState(false);   // the name field turns red only after a Sign press without one
  const sign = async () => {
    if (!shiftId) return;
    if (!by.trim()) { setTried(true); return; }
    setBusy(true);
    const r = await post("/tools/record_sign", { by: by.trim(), shift_id: shiftId });
    setBusy(false);
    setResult({ what: `Sign ${shiftId}`, ok: r.ok, error: r.error });   // a second signature's refusal is shown as the API wrote it
  };

  const d = rec.data ? redactDeep(rec.data) : undefined;   // the record is filmed: no handle or email ever reaches the page
  const reading = (!!shiftId && !d && !rec.error) || (!shiftId && !shifts.data && !shifts.error);   // a skeleton, never "No run yet" or "Unsigned" before the read
  return (
    <div className="flex flex-col gap-4">
      <PageActions>
        {run.error ? <SignalChip tone="alert">Run · FAILED {redact(run.error)}</SignalChip>
          : run.data && <SignalChip tone="neutral">Run in force · {run.data.shift_id}</SignalChip>}
        <span className="ml-auto flex items-center gap-2">
          <Select value={shiftId ?? ""} onValueChange={setPicked} disabled={!shifts.data?.shifts.length}>
            <SelectTrigger aria-label="Run" className="h-9 w-[190px] border-input bg-card text-[13px] shadow-none"><SelectValue placeholder="No runs yet" /></SelectTrigger>
            <SelectMenu>
              {(shifts.data?.shifts ?? []).map((s) => <SelectItem key={s} value={s} className="text-[13px]">{s}{s === shifts.data?.current ? " · in force" : ""}</SelectItem>)}
            </SelectMenu>
          </Select>
          <ActionButton intent="secondary" disabled={busy} onClick={() => start("morning")}>Start morning run</ActionButton>
          <ActionButton intent="secondary" disabled={busy} onClick={() => start("night")}>Start night run</ActionButton>
        </span>
      </PageActions>
      <Results rows={[result]} />
      {shifts.error && <p role="alert" className="font-mono text-[12px] text-signal-alert">runs · FAILED {redact(shifts.error)}</p>}
      {d && d.stub_rows > 0 && (
        <div role="status" className="rounded-md border border-heat-peak bg-card px-4 py-2 font-mono text-[12px] text-foreground">
          {d.stub_rows} of {d.rows} rows are cached/stub: a fixture, not a night
        </div>
      )}

      <div className="grid grid-cols-12 gap-4">
        <Module title={shiftId ? `The record · ${shiftId}` : "The record"} size="auto" className="col-span-12 lg:col-span-8"
          meta={d ? `${d.window.from.replace("T", " ")} → ${d.window.to.replace("T", " ")}` : undefined}
          error={rec.error ? `FAILED ${redact(rec.error)}` : !shiftId && shifts.error ? `FAILED ${redact(shifts.error)}` : undefined}
          loading={reading}>
          {!shiftId ? <p className="text-[15px] text-muted-foreground">{listed.length ? "No run in force yet. Start a morning or a night run, or pick a past run above." : "No run yet. Start a morning or a night run, then walk the route."}</p> : d && <RecordBody d={d} />}{/* only when /record/shifts answered with none */}
        </Module>

        <div className="col-span-12 flex flex-col gap-4 lg:col-span-4">
          <Module title="Signature" size="auto" loading={reading}>
            <div className="flex flex-col gap-2">
              {d?.signed
                ? <SignalChip tone="good" className="self-start">Signed by {d.signed.by} · {d.signed.at.replace("T", " ")}</SignalChip>
                : <WaitingChip className="self-start">Unsigned</WaitingChip>}
              <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
                Your name
                <Input value={by} placeholder="required to sign" aria-invalid={tried && !d?.signed && !by.trim()} disabled={!!d?.signed} className="h-8 max-w-[200px] text-[13px]"
                  onChange={(e) => { setBy(e.target.value); localStorage.setItem("wtdd.scout.by", e.target.value); }} />
              </label>
              <ActionButton intent="primary" className="self-start" disabled={busy || !shiftId || !!d?.signed}
                title={d?.signed ? "Signed once; a second signature is refused" : undefined} onClick={sign}>Sign this record</ActionButton>
              <p className="text-[13px] text-muted-foreground">A robot cannot be the OSHA competent person. This record is theirs to sign.</p>
            </div>
          </Module>
          <Report evals={evals.data} error={evals.error} />
        </div>
      </div>
    </div>
  );
}

function RecordBody({ d }: { d: RecordJson }) {
  const bad = (s: string | null | undefined) => s && <span className="text-signal-alert">{s}</span>;
  const twoDays = d.window.from.slice(0, 10) !== d.window.to.slice(0, 10);
  const trouble = [...d.refusals, ...d.failures].sort((a, b) => a.ts.localeCompare(b.ts));   // one list, in time order
  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-2">
        <h3 className="text-[13px] font-medium">Stops</h3>
        {d.stops.length === 0 ? <p className="text-[15px] text-muted-foreground">No stop in this run.</p> : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                {["#", "Time", "Look", "What it saw", "Asked", "Corrected"].map((h) => <TableHead key={h} className="text-[13px] text-muted-foreground">{h}</TableHead>)}
              </TableRow>
            </TableHeader>
            <TableBody>
              {d.stops.map((s) => (
                <TableRow key={s.n}>
                  <TableCell className="font-mono text-[12px]">{s.n}</TableCell>
                  <TableCell className="font-mono text-[12px] text-muted-foreground">{when(s.ts, twoDays)}</TableCell>
                  <TableCell className="font-mono text-[12px]">{s.kind ?? "none"}</TableCell>
                  <TableCell className="max-w-[360px] whitespace-normal text-[13px]">{s.ok ? s.sentence : bad(s.error)}{s.person ? <SignalChip tone="neutral" className="ml-2">person</SignalChip> : null}</TableCell>
                  <TableCell className="text-[13px]">{s.pinged ? "yes" : "no"}</TableCell>
                  <TableCell className="max-w-[200px] whitespace-normal text-[13px]">{s.correction ?? ""}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="text-[13px] font-medium">Flags to the group</h3>
        {d.flags.length === 0 ? <p className="text-[15px] text-muted-foreground">Nothing was flagged.</p> : d.flags.map((f) => (
          <div key={f.ts + f.trigger} className="flex flex-col gap-1 border-t border-border pt-2 first:border-t-0 first:pt-0 text-[13px]">
            <span><span className="font-mono text-[12px] text-muted-foreground">{when(f.ts, twoDays)}</span> · {f.text}</span>
            {f.resolved
              ? <span className="text-muted-foreground">{f.resolved.by}: “{f.resolved.text}” · {f.resolved.verdict}{secs(f.resolved.acked_ms) ? ` · answered after ${secs(f.resolved.acked_ms)}` : ""}{secs(f.resolved.closed_ms) ? ` · closed after ${secs(f.resolved.closed_ms)}` : ""}</span>
              : <span className="text-signal-alert">unanswered</span>}
          </div>
        ))}
      </section>

      {d.corrections.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="text-[13px] font-medium">Corrections</h3>
          {d.corrections.map((c) => (
            <p key={c.ts} className="text-[13px]">{c.by}: “{c.text}”{secs(c.acked_ms) ? <span className="text-muted-foreground"> · after {secs(c.acked_ms)}</span> : null}</p>
          ))}
        </section>
      )}

      {(d.refusals.length > 0 || d.failures.length > 0) && (
        <section className="flex flex-col gap-1">
          <h3 className="text-[13px] font-medium">Refusals and failures</h3>
          {trouble.map((r) => (
            <p key={r.ts + r.tool} className="font-mono text-[12px] text-signal-alert">{when(r.ts, twoDays)} · {r.tool} · {r.error}</p>
          ))}
        </section>
      )}
      {d.after_signature.length > 0 && (
        <p className="font-mono text-[12px] text-signal-alert">{d.after_signature.length} posts came after the signature and are not part of this record.</p>
      )}
    </div>
  );
}

/** G3: the report as evals.json holds it, with its own written time; it is never said to have graded this run. */
function Report({ evals, error }: { evals?: Evals; error?: string }) {
  const rows = evals?.rows ?? [];
  return (
    <Module title="Report" size="auto" meta={evals?.written ? `evals.json · written ${evals.written}` : undefined} error={error ? `FAILED ${redact(error)}` : undefined} loading={!evals && !error}>
      {rows.length === 0 ? <p className="text-[15px] text-muted-foreground">No graded trials yet. They are written by the evals, not by this page.</p> : (
        <div className="flex flex-col gap-2">
          {rows.map((r) => (
            <div key={`${r.scenario}-${r.trial}`} className="flex items-baseline gap-2 text-[13px]">
              <SignalChip tone={r.grade === "pass" ? "good" : "alert"}>{r.grade}</SignalChip>
              <span className="font-mono text-[12px]">{r.scenario} · {r.trial}</span>
              <span className="truncate text-muted-foreground" title={r.detail}>{r.ran}</span>
            </div>
          ))}
          <p className="text-[13px] text-muted-foreground">Graded when evals.json was written, not from the record above.</p>
        </div>
      )}
    </Module>
  );
}
