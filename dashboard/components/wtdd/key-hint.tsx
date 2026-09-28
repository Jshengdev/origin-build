import { cn } from "@/lib/utils";

/** Keyboard shortcut shown inside a button. Mono, sharp corners (rounded-sm = 3px). The shortcut must actually work. */
export function KeyHint({ children, onInk = false, className }: { children: string; onInk?: boolean; className?: string }) {
  return (
    <kbd
      className={cn(
        "rounded-sm border px-1.5 font-mono text-[12px] leading-4 font-normal",
        onInk ? "border-muted-foreground text-primary-foreground" : "border-border text-muted-foreground",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
