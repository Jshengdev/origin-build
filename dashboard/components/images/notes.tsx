"use client";
import { Fragment, useRef, useState } from "react";
import { toast } from "sonner";
import { ActionButton, Avatar, Module } from "@/components/wtdd";
import { useApp } from "@/components/shell/app-state";
import { dayTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Notes on one point's images, with @mentions. A mention puts the note in that person's Waiting queue. */
export function Notes({ routineId, stepId }: { routineId: string; stepId: string }) {
  const { notes, people, addNote, me } = useApp();
  const mine = notes.filter((n) => n.routineId === routineId && n.stepId === stepId).sort((a, b) => a.at.localeCompare(b.at));
  const [text, setText] = useState("");
  const [picking, setPicking] = useState(0);
  const box = useRef<HTMLTextAreaElement>(null);

  /** "@Ro" at the caret opens the people list, filtered. */
  const query = text.match(/@([\w-]*)$/)?.[1];
  const matches = query == null ? [] : people.filter((p) => p.id !== me && p.name.toLowerCase().startsWith(query.toLowerCase()));

  const mention = (name: string) => {
    setText((t) => t.replace(/@[\w-]*$/, `@${name} `));
    setPicking(0);
    box.current?.focus();
  };
  const post = () => {
    if (!text.trim()) return;
    const mentioned = people.filter((p) => text.includes(`@${p.name}`)).map((p) => p.name);
    addNote({ routineId, stepId, text: text.trim() });
    setText("");
    toast("Note added", mentioned.length ? { description: `Sent to ${mentioned.join(", ")}` } : undefined);
  };

  return (
    <Module title="Notes" size="full" meta={mine.length ? `${mine.length}` : undefined}>
      <div className="flex flex-col gap-4">
        {mine.length === 0 && <p className="text-[15px] text-muted-foreground">No notes yet. Tag someone with @ to send it to them.</p>}
        {mine.map((n) => {
          const author = people.find((p) => p.id === n.authorId)?.name ?? "Someone";
          return (
            <div key={n.id} className="flex gap-3">
              <Avatar name={author} size={28} />
              <div className="flex flex-col gap-1">
                <span className="flex items-baseline gap-2 text-[13px]"><span className="font-medium">{author}</span><span className="text-muted-foreground">{dayTime(n.at)}</span></span>
                <p className="text-[15px] leading-[22px]"><WithMentions text={n.text} names={people.map((p) => p.name)} /></p>
              </div>
            </div>
          );
        })}

        <div className="flex flex-col gap-2 border-t border-border pt-4">
          <div className="relative">
          <textarea
            ref={box}
            value={text}
            onChange={(e) => { setText(e.target.value); setPicking(0); }}
            onKeyDown={(e) => {
              if (matches.length) {
                if (e.key === "ArrowDown") { e.preventDefault(); setPicking((i) => (i + 1) % matches.length); return; }
                if (e.key === "ArrowUp") { e.preventDefault(); setPicking((i) => (i - 1 + matches.length) % matches.length); return; }
                if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); mention(matches[picking].name); return; }
              }
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); post(); }
            }}
            rows={2}
            placeholder="Add a note. Type @ to tag someone."
            aria-label="Note"
            className="w-full resize-none rounded-md border border-input bg-card px-3 py-2 text-[15px] leading-[22px] outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
          />
          {matches.length > 0 && (
            <ul role="listbox" aria-label="People" className="absolute left-0 top-full z-10 mt-1 w-64 rounded-md border border-border bg-popover p-1 shadow-[0_8px_24px_rgb(0_0_0/0.12)]">
              {matches.map((p, i) => (
                <li key={p.id} role="option" aria-selected={i === picking}>
                  <button
                    type="button"
                    onMouseDown={(e) => { e.preventDefault(); mention(p.name); }}
                    className={cn("flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[13px]", i === picking && "bg-accent")}
                  >
                    <Avatar name={p.name} size={20} />{p.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
          </div>
          <ActionButton intent="primary" className="self-start" disabled={!text.trim()} onClick={post}>Add note</ActionButton>
        </div>
      </div>
    </Module>
  );
}

/** Mentions of known people in the note, set in medium weight. */
function WithMentions({ text, names }: { text: string; names: string[] }) {
  const parts = names.length ? text.split(new RegExp(`(@(?:${names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")}))`)) : [text];
  return <>{parts.map((p, i) => (p.startsWith("@") && names.includes(p.slice(1)) ? <span key={i} className="font-medium">{p}</span> : <Fragment key={i}>{p}</Fragment>))}</>;
}
