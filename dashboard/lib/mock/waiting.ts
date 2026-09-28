/** Mock "waiting on a person" items and image notes. Every item names who it waits on. */
export type WaitKind = "ask" | "zone" | "routine" | "mention";

export interface WaitItem {
  id: string;
  kind: WaitKind;
  personId: string;
  since: string;
  title: string;
  detail?: string;
  image?: string;
  href?: string;
  zoneId?: string;
  routineId?: string;
}

export interface Note { id: string; routineId: string; stepId: string; authorId: string; text: string; at: string }

export const INITIAL_NOTES: Note[] = [
  {
    id: "n1", routineId: "progress-check", stepId: "p1", authorId: "alex", at: "2026-09-26T17:05:00Z",
    text: "More boxes stacked by the back wall since Sep 20. @Robin Stand-in can you check it's not blocking the vent?",
  },
];

export const INITIAL_WAITING: WaitItem[] = [
  {
    id: "w-ask-s2", kind: "ask", personId: "oncall", since: "2026-09-26T23:02:55Z",
    title: "Socks on the living room floor", detail: "The dog asked: leave them or flag for pickup?",
    image: "/fixtures/images/look_s2.svg", href: "/sessions/14",
  },
  {
    id: "w-zone-prop-1", kind: "zone", personId: "robin", since: "2026-09-26T23:04:10Z",
    title: "Proposed zone: blob by the couch", detail: "The dog flagged it. Nothing is refused until someone makes it a rule.",
    zoneId: "prop-1", href: "/driving",
  },
  {
    id: "w-note-n1", kind: "mention", personId: "robin", since: "2026-09-26T17:05:00Z",
    title: "Alex Stand-in mentioned you on Back wall", detail: "More boxes stacked by the back wall since Sep 20.",
    href: "/images/progress-check/p1",
  },
];
