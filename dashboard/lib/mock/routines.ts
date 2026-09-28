/**
 * Mock routines for the mockup. Invented, in the product's vocabulary. The real source is the taught route
 * and item 21's tapped routes; a routine here is an ordered list of points on the map, each with one action.
 */
import stops from "@/lib/data/fixtures/stops.json";
import type { Fixture, Stop } from "@/lib/data";

export type Action = "photo" | "look_level" | "look_nod" | "sit" | "check_people" | "lights_on";

export const ACTIONS: Array<{ value: Action; label: string }> = [
  { value: "photo", label: "Take a photo" },
  { value: "look_level", label: "Look level" },
  { value: "look_nod", label: "Look down" },
  { value: "check_people", label: "Check for people" },
  { value: "lights_on", label: "Turn the lights on" },
  { value: "sit", label: "Sit and wait" },
];
export const actionLabel = (a: Action) => ACTIONS.find((x) => x.value === a)?.label ?? a;
/** Actions that leave an image behind. */
export const TAKES_IMAGE: Action[] = ["photo", "look_level", "look_nod", "check_people"];

export interface RoutineStep { id: string; name: string; position: [number, number]; action: Action }
/** Who walks it: the robot, or a person (the dog's route as a checklist for someone on site). */
export type Assignee = { kind: "robot" } | { kind: "person"; personId: string };
export interface Routine { id: string; name: string; steps: RoutineStep[]; assignee: Assignee; lastRun?: string }

const s = (f: unknown) => (f as Fixture<Stop[]>).data;
const byId = Object.fromEntries(s(stops).map((x) => [x.id, x]));
const step = (id: string, action: Action): RoutineStep => ({ id, name: byId[id].name.replace(/\s*\(.*\)$/, ""), position: byId[id].position, action });

export const INITIAL_ROUTINES: Routine[] = [
  {
    id: "night-round",
    name: "Night round",
    assignee: { kind: "robot" },
    lastRun: "2026-09-26T23:00:06Z",
    steps: [step("s1", "check_people"), step("s2", "look_nod"), step("s3", "photo"), step("s4", "look_nod")],
  },
  {
    id: "progress-check",
    name: "Progress check",
    assignee: { kind: "robot" },
    lastRun: "2026-09-25T16:30:00Z",
    steps: [
      { id: "p1", name: "Back wall", position: [13.5, 9.6], action: "photo" },
      { id: "p2", name: "Kitchen counter", position: [3.5, 7.5], action: "photo" },
      { id: "p3", name: "Hallway", position: [9, 3.8], action: "photo" },
    ],
  },
  {
    id: "opening-walkthrough",
    name: "Opening walkthrough",
    assignee: { kind: "person", personId: "alex" },
    steps: [
      { id: "o1", name: "Gate", position: [6.3, 0.8], action: "check_people" },
      { id: "o2", name: "Kitchen counter", position: [3.5, 7.5], action: "photo" },
      { id: "o3", name: "Back wall", position: [13.5, 9.6], action: "photo" },
    ],
  },
];
