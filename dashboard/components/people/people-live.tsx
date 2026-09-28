"use client";
/**
 * People on the live API (#72, GET /people; Johnny: "let's keep people"): the group chat's name and the housemates' first
 * names, as served. Names only: the API never answers a handle, and every string still goes through redact() here.
 * An empty group says the API's why; a failed read is FAILED, never the mock roster (components/people/people-view.tsx,
 * which stays in Storybook). Roles (on call, driver, ...) are not served, so none are shown.
 */
import { Avatar, Module } from "@/components/wtdd";
import { redact, usePoll, type PeopleJson } from "@/lib/data/api";

export function PeopleLive() {
  const people = usePoll<PeopleJson>("/people", 10000);
  const p = people.data;
  return (
    <div className="grid grid-cols-12 gap-4">
      <Module title="The group" meta={p ? (p.group ? redact(p.group) : `no group · ${redact(p.group_why ?? "not served")}`) : undefined} size="auto"
        className="col-span-12 lg:col-span-6" loading={!p && !people.error} error={people.error ? `FAILED GET /people · ${redact(people.error)}` : undefined}>
        {p && (p.people.length ? (
          <ul className="flex flex-col">
            {p.people.map((x) => (
              <li key={x.name} className="flex items-center gap-3 border-t border-border py-2.5 first:border-t-0 first:pt-0">
                <Avatar name={redact(x.name)} />
                <span className="text-[14px]">{redact(x.name)}</span>
              </li>
            ))}
          </ul>
        ) : <p className="text-[13px] text-muted-foreground">No one in the group yet · {redact(p.why ?? "none served")}</p>)}
      </Module>
    </div>
  );
}
