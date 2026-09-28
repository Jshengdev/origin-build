"use client";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { ActionButton, Avatar, Module, SignalChip } from "@/components/wtdd";
import { PageActions, PageHeader } from "@/components/shell/page-header";
import { useApp } from "@/components/shell/app-state";
import type { WaitItem } from "@/lib/mock/waiting";
import { dayTime } from "@/lib/format";

const KIND: Record<WaitItem["kind"], string> = { ask: "Question from the dog", zone: "Proposed zone", routine: "Routine to walk", mention: "Mention" };

/** Everything waiting on a person: the dog's questions, proposed zones, routines assigned to people, mentions. */
export function WaitingView() {
  const { waiting, people, me } = useApp();
  const [scope, setScope] = useState<"me" | "all">("all");
  const items = [...waiting].filter((w) => scope === "all" || w.personId === me).sort((a, b) => b.since.localeCompare(a.since));

  return (
    <>
      <PageHeader crumbs={[{ label: "Waiting" }]} />
      <div className="flex flex-col gap-4">
        <PageActions>
          <ToggleGroup type="single" variant="outline" value={scope} onValueChange={(v) => v && setScope(v as "me" | "all")} aria-label="Whose">
            <ToggleGroupItem value="all" className="px-3 text-[13px]">Everyone</ToggleGroupItem>
            <ToggleGroupItem value="me" className="px-3 text-[13px]">Waiting on me</ToggleGroupItem>
          </ToggleGroup>
        </PageActions>

        {items.length === 0 ? (
          <Module title="Waiting" size="full" className="py-12 text-center [&>[data-slot=card-header]]:hidden">
            <p className="text-[15px] text-muted-foreground">Nothing is waiting on {scope === "me" ? "you" : "anyone"}.</p>
          </Module>
        ) : (
          <div className="flex flex-col gap-3">
            {items.map((w) => <Item key={w.id} item={w} person={people.find((p) => p.id === w.personId)?.name ?? "Someone"} />)}
          </div>
        )}
      </div>
    </>
  );
}

function Item({ item: w, person }: { item: WaitItem; person: string }) {
  const { resolve, confirmZone } = useApp();
  const [reply, setReply] = useState("");
  return (
    <Module title={w.title} size="full" actions={<span className="flex items-center gap-2 text-[13px] text-muted-foreground"><Avatar name={person} size={22} />{person} · {dayTime(w.since)}</span>}>
      <div className="flex flex-col gap-3 md:flex-row md:items-start">
        {w.image && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={w.image} alt="" className="aspect-[16/10] w-full shrink-0 rounded-md object-cover md:w-48" />
        )}
        <div className="flex flex-1 flex-col gap-3">
          <span className="flex items-center gap-2">
            <SignalChip tone="neutral">{KIND[w.kind]}</SignalChip>
          </span>
          {w.detail && <p className="text-[15px] leading-[22px]">{w.detail}</p>}

          {w.kind === "ask" && (
            <form
              className="flex gap-2"
              onSubmit={(e) => { e.preventDefault(); if (!reply.trim()) return; resolve(w.id); toast("Reply sent", { description: `“${reply.trim()}”` }); }}
            >
              <Input value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Reply to the dog" aria-label="Reply" className="h-9 max-w-md border-input bg-card shadow-none" />
              <ActionButton intent="person" type="submit" disabled={!reply.trim()}>Send reply</ActionButton>
            </form>
          )}
          <div className="flex flex-wrap gap-2">
            {w.kind === "zone" && w.zoneId && (
              <ActionButton intent="person" onClick={() => { confirmZone(w.zoneId!); toast("Made it a rule"); }}>Make it a rule</ActionButton>
            )}
            {w.kind === "routine" && (
              <ActionButton intent="person" onClick={() => { resolve(w.id); toast("Marked done"); }}>Mark walked</ActionButton>
            )}
            {w.kind === "mention" && (
              <ActionButton intent="secondary" onClick={() => { resolve(w.id); toast("Marked done"); }}>Mark done</ActionButton>
            )}
            {w.href && <ActionButton intent="quiet" asChild><Link href={w.href}>Open</Link></ActionButton>}
            {w.kind === "zone" && <ActionButton intent="quiet" onClick={() => resolve(w.id)}>Dismiss</ActionButton>}
          </div>
        </div>
      </div>
    </Module>
  );
}
