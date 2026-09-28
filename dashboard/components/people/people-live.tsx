"use client";
/**
 * People on the live API (feat/people-cards; Johnny, 20:0x: "for the peoples tab show the group chat and each sub card
 * with each individual in there"): one card for the group chat (its name, how many members, its last message, and the
 * listener's status from GET /chat), then one card per member: its label ("you", a first name the person agreed to, else
 * "member N"; the API never answers a handle), messages in the last 24 h, when last seen, and replies to the dog. "you"
 * first. Every string is redacted again here. A failed read is FAILED, never the mock roster (people-view.tsx, Storybook).
 */
import { Avatar, Module } from "@/components/wtdd";
import { CastleChip } from "@/components/overview/overview-live";
import { redact, usePoll, type Chat, type PeopleJson } from "@/lib/data/api";

/** "09-27 19:42": the served local time with its day, so a last seen yesterday never reads as today. */
const when = (ts: string) => ts.replace("T", " ").slice(5, 16);

export function PeopleLive() {
  const people = usePoll<PeopleJson>("/people", 10000);
  const chat = usePoll<Chat>("/chat", 3000);
  const p = people.data;
  const members = p ? [...p.people].sort((a, b) => Number(b.is_me) - Number(a.is_me)) : [];   // "you" first, the rest as served
  return (
    <div className="flex flex-col gap-4">
      <Module title={p?.group.name ? redact(p.group.name) : "The group chat"} size="auto"
        meta={p ? `${p.group.members} ${p.group.members === 1 ? "member" : "members"}${p.group.last_ts ? ` · last message ${when(p.group.last_ts)}` : " · no message yet"}` : undefined}
        loading={!p && !people.error} error={people.error ? `FAILED GET /people · ${redact(people.error)}` : undefined}>
        <CastleChip chat={chat.data} error={chat.error ? redact(chat.error) : undefined} />
      </Module>
      {p && (members.length ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {members.map((m) => (
            <Module key={m.id} title={redact(m.label)} size="auto">
              <div className="flex items-start gap-3">
                <Avatar name={redact(m.label)} size={32} />
                <dl className="grid flex-1 grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[13px]">
                  <dt className="text-muted-foreground">Messages, 24 h</dt><dd className="font-mono">{m.messages_24h}</dd>
                  <dt className="text-muted-foreground">Last seen</dt><dd className="font-mono">{m.last_ts ? when(m.last_ts) : "not yet"}</dd>
                  <dt className="text-muted-foreground">Replies to the dog</dt><dd className="font-mono">{m.replies_to_dog}</dd>
                </dl>
              </div>
            </Module>
          ))}
        </div>
      ) : <p className="text-[13px] text-muted-foreground">No member served for this group.</p>)}
    </div>
  );
}
