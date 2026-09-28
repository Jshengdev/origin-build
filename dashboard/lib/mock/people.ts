/**
 * Mock people. Stand-in names only: nobody real is named in fixtures (team rule). "Sam Stand-in" matches the
 * team's dry screenshots. The signed-in user is Robin Stand-in.
 */
export type Role = "on_call" | "driver" | "editor" | "viewer";
export type Channel = "imessage_1to1" | "imessage_group" | "sms";

export interface Member { id: string; name: string; role: Role; channel: Channel; quietHours?: string }

export const ROLES: Array<{ value: Role; label: string; can: string }> = [
  { value: "on_call", label: "On call", can: "Gets the dog's questions" },
  { value: "driver", label: "Driver", can: "Can drive the dog" },
  { value: "editor", label: "Editor", can: "Can change routines and zones" },
  { value: "viewer", label: "Viewer", can: "Can look" },
];
export const roleLabel = (r: Role) => ROLES.find((x) => x.value === r)?.label ?? r;
export const CHANNELS: Record<Channel, string> = { imessage_1to1: "iMessage", imessage_group: "iMessage group", sms: "SMS" };

export const ME = "robin";

export const INITIAL_PEOPLE: Member[] = [
  { id: "oncall", name: "Sam Stand-in", role: "on_call", channel: "imessage_1to1", quietHours: "12 AM to 6 AM" },
  { id: "alex", name: "Alex Stand-in", role: "driver", channel: "sms" },
  { id: "robin", name: "Robin Stand-in", role: "editor", channel: "imessage_1to1" },
  { id: "jo", name: "Jo Stand-in", role: "viewer", channel: "sms", quietHours: "10 PM to 7 AM" },
];

export const GROUP = { id: "group", name: "THE CASTLE (house group)", channel: "imessage_group" as Channel };

export const initials = (name: string) => name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
