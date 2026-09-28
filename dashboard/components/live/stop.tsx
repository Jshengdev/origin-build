"use client";
/**
 * Stop, the same on every page that can start a walk. It is never disabled and never waits on anything: POST /dog/stop and
 * POST /field/stop go out at once, each with its own 3 s timeout, so one failing never skips the other (today's remote
 * always sends both; v2 must never be less safe). Each shows its own ok or red FAILED line.
 */
import { useState } from "react";
import { ActionButton, SignalChip } from "@/components/wtdd";
import { post, redact } from "@/lib/data/api";

export type Result = { what: string; ok: boolean; error?: string } | null;

export function useStop() {
  const [stopped, setStopped] = useState<Result[]>([]);
  const stop = async () => {
    setStopped(await Promise.all(["/dog/stop", "/field/stop"].map(async (path) => {
      const r = await post(path, {}, 3000);
      return { what: `Stop · POST ${path}`, ok: r.ok, error: r.error };
    })));
  };
  const button = <ActionButton intent="secondary" onClick={stop}>Stop</ActionButton>;
  return { stopped, button };
}

/** One line per result: ok, or a red FAILED with its reason (redacted). */
export function Results({ rows }: { rows: Result[] }) {
  return (
    <>
      {rows.map((r, i) => r && (
        <p key={i} role={r.ok ? "status" : "alert"} className="flex items-baseline gap-2 font-mono text-[12px]">
          {r.ok ? <SignalChip tone="neutral">ok</SignalChip> : <SignalChip tone="alert">FAILED</SignalChip>}
          <span className={r.ok ? "text-muted-foreground" : "text-signal-alert"}>{r.what}{r.error ? ` · ${redact(r.error)}` : ""}</span>
        </p>
      ))}
    </>
  );
}
