"use client";
/**
 * "Save as routine" (#71's POST /routines {action: "save", name}): the map's saved route (path, stops, actions) kept under
 * a name, a name already saved replaced. One form, on Paths and on Routines (Johnny, 19:4x: parity). The line under it is
 * what is on the map now; a refusal is the page's FAILED line. `locked` holds it (an unsaved edit on Paths: the routine
 * is the saved map, never the edit). `after` gets the answer (Routines re-reads its list).
 */
import { useState } from "react";
import { Input } from "@/components/ui/input";   // stock shadcn
import { ActionButton, Module } from "@/components/wtdd";
import { post, type MapJson } from "@/lib/data/api";
import type { Result } from "@/components/live/stop";

export function SaveAsRoutine({ served, loaded, locked, onResult, after }: {
  served?: MapJson | null; loaded?: string | null; locked?: string; onResult: (r: Result) => void;
  after?: (r: { ok: boolean; error?: string; [k: string]: unknown }) => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const dots = served?.path?.length ?? 0, stops = served?.stops?.length ?? 0;
  const save = async () => {
    const n = name.trim();
    setBusy(true);
    const r = await post("/routines", { action: "save", name: n });
    setBusy(false);
    onResult(r.ok ? { what: `Save as routine · ${n}`, ok: true } : { what: `Save as routine · ${n}`, ok: false, error: r.error });
    if (r.ok) setName("");
    after?.(r);
  };
  return (
    <Module title="Save as routine" size="auto">
      <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim() && dots && !locked) save(); }}>
        <div className="flex items-center gap-2">
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} placeholder="a name, e.g. kitchen to bedroom 2" aria-label="Routine name" />
          <ActionButton type="submit" intent="secondary" disabled={busy || !name.trim() || !dots || !!locked}
            title={locked ?? (!dots ? "The map has no path: draw it on Paths first" : "POST /routines save: the saved route, its stops and their actions")}>Save as</ActionButton>
        </div>
        <span className="font-mono text-[12px] text-muted-foreground">
          {served ? `on the map now: ${dots} dots · ${stops} ${stops === 1 ? "stop" : "stops"}${loaded ? ` · ${loaded}` : ""}` : "the map has not loaded"}
        </span>
      </form>
    </Module>
  );
}
