import { LayoutGrid, Inbox, Route, FileSignature, ListChecks, Settings, Radio, Gamepad2, Users, type LucideIcon } from "lucide-react";

export interface NavEntry { href: string; label: string; icon: LucideIcon; key: string; faded?: boolean }

/**
 * `key` is the second key of the G-then-key shortcut. Johnny, 17:15: Overview · Paths · Routines · Waiting · Record ·
 * Settings ("keep routines and settings because we need to come back to them"), and People ("let's keep people").
 * Routines, People and Settings (Monitoring) read the API.
 */
export const NAV: NavEntry[] = [
  { href: "/", label: "Overview", icon: LayoutGrid, key: "O" },
  { href: "/paths", label: "Paths", icon: Route, key: "T" },
  { href: "/routines", label: "Routines", icon: ListChecks, key: "U" },
  { href: "/waiting", label: "Waiting", icon: Inbox, key: "W" },
  { href: "/record", label: "Record", icon: FileSignature, key: "R" },
  { href: "/people", label: "People", icon: Users, key: "P" },   // live on GET /people (Johnny: "let's keep people")
];

/**
 * Back as samples (Johnny, 17:3x: "i really liked those things and i want to bring them back so i can be more specific
 * about what it should and shouldnt display"): v2's other screens, in their own sidebar group, each page marked "Sample ·
 * not live yet" and greyed. Where their live parts are today: the camera and the drive switch on Overview, a run's
 * record on Record, the dog's health on Overview's Body card, the group's asks on Waiting.
 */
export const SAMPLES: NavEntry[] = [
  // Johnny: "driving can be faded and live can be faded": their live parts are on Overview (the camera, the drive switch).
  // Monitoring is live inside Settings, Sessions inside Record, and the photos inside Routines and Waiting.
  { href: "/live", label: "Live", icon: Radio, key: "L", faded: true },
  { href: "/driving", label: "Driving", icon: Gamepad2, key: "D", faded: true },
];

export const SETTINGS: NavEntry = { href: "/settings", label: "Settings", icon: Settings, key: "S" };
