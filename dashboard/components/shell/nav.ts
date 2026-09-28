import { LayoutGrid, Inbox, Route, FileSignature, ListChecks, Settings, Radio, Gamepad2, History, Activity, Image as ImageIcon, Users, type LucideIcon } from "lucide-react";

export interface NavEntry { href: string; label: string; icon: LucideIcon; key: string }

/**
 * `key` is the second key of the G-then-key shortcut. Johnny, 17:15: Overview · Paths · Routines · Waiting · Record ·
 * Settings ("keep routines and settings because we need to come back to them"). Settings is not wired yet
 * and say so on the page (components/shell/sample-frame.tsx).
 */
export const NAV: NavEntry[] = [
  { href: "/", label: "Overview", icon: LayoutGrid, key: "O" },
  { href: "/paths", label: "Paths", icon: Route, key: "T" },
  { href: "/routines", label: "Routines", icon: ListChecks, key: "U" },
  { href: "/waiting", label: "Waiting", icon: Inbox, key: "W" },
  { href: "/record", label: "Record", icon: FileSignature, key: "R" },
];

/**
 * Back as samples (Johnny, 17:3x: "i really liked those things and i want to bring them back so i can be more specific
 * about what it should and shouldnt display"): v2's other screens, in their own sidebar group, each page marked "Sample ·
 * not live yet" and greyed. Where their live parts are today: the camera and the drive switch on Overview, a run's
 * record on Record, the dog's health on Overview's Body card, the group's asks on Waiting.
 */
export const SAMPLES: NavEntry[] = [
  { href: "/live", label: "Live", icon: Radio, key: "L" },
  { href: "/driving", label: "Driving", icon: Gamepad2, key: "D" },
  { href: "/sessions", label: "Sessions", icon: History, key: "E" },
  { href: "/monitoring", label: "Monitoring", icon: Activity, key: "M" },
  { href: "/images", label: "Images", icon: ImageIcon, key: "I" },
  { href: "/people", label: "People", icon: Users, key: "P" },
];

export const SETTINGS: NavEntry = { href: "/settings", label: "Settings", icon: Settings, key: "S" };
