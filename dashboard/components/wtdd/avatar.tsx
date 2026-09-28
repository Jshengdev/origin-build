import { cn } from "@/lib/utils";

const initialsOf = (name: string) => name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

/** A person: initials on a quiet fill. Never a status color. */
export function Avatar({ name, size = 24, className }: { name: string; size?: number; className?: string }) {
  return (
    <span
      title={name}
      aria-label={name}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.42) }}
      className={cn("inline-flex shrink-0 select-none items-center justify-center rounded-full bg-accent font-medium text-foreground ring-2 ring-card", className)}
    >
      {initialsOf(name)}
    </span>
  );
}

/** Overlapping avatars, e.g. who is watching Live. */
export function AvatarStack({ names, size = 24, className }: { names: string[]; size?: number; className?: string }) {
  return (
    <span className={cn("flex items-center", className)}>
      {names.map((n, i) => <Avatar key={n} name={n} size={size} className={i ? "-ml-1.5" : undefined} />)}
    </span>
  );
}
