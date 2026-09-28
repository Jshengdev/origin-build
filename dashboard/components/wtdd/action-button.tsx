"use client";
import * as React from "react";
import { Button } from "@/components/ui/button";          // stock shadcn, never edited
import { cn } from "@/lib/utils";
import { type Stage, stageLabel } from "./stage";

/**
 * The design system's button, as a wrapper over stock shadcn <Button>.
 * Intents:
 *   primary   ink fill. At most one per view. Disabled, it goes quiet  -> shadcn "default"
 *             (a line edge, muted text), never a 50% grey slab.
 *   secondary surface fill with a line-strong edge (3:1).             -> shadcn "outline" + border-input
 *   person    highlight fill. Only where a person must act:           -> shadcn "default" + highlight classes
 *             "Sign this record", "Make it a rule", "Answer the ask".
 *   quiet     text-only actions.                                       -> shadcn "ghost"
 *   danger    soft alert chip style (passes contrast in both themes).  -> shadcn "outline" + signal classes
 * A `stage` of not_built disables the button and shows the status word as its title.
 * Buttons carry no key hints: shortcuts work, but they are not shown inside buttons.
 */
type Intent = "primary" | "secondary" | "person" | "quiet" | "danger";

const intentToVariant = { primary: "default", secondary: "outline", person: "default", quiet: "ghost", danger: "outline" } as const;

const intentClass: Record<Intent, string> = {
  primary: "hover:bg-primary/75 disabled:border disabled:border-border disabled:bg-transparent disabled:text-muted-foreground disabled:opacity-100",
  secondary: "bg-card border-input hover:bg-foreground/10",
  person: "bg-highlight text-on-highlight hover:bg-highlight/75",
  quiet: "",
  danger: "bg-signal-alert-soft text-signal-alert border-transparent hover:bg-signal-alert-soft/80",
};

export interface ActionButtonProps extends Omit<React.ComponentProps<typeof Button>, "variant"> {
  intent?: Intent;
  stage?: Stage;
}

export function ActionButton({ intent = "secondary", stage, className, children, disabled, title, ...props }: ActionButtonProps) {
  const notBuilt = stage?.kind === "not_built" || stage?.kind === "building";
  return (
    <Button
      variant={intentToVariant[intent]}
      disabled={disabled || notBuilt}
      title={notBuilt && stage ? stageLabel(stage) : title}
      className={cn(
        "shadow-none text-[13px] font-medium",
        // DS focus: 2px line-strong ring with a 2px offset, replacing shadcn's 3px ring at 50%
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        intentClass[intent],
        className,
      )}
      {...props}
    >
      {children}
    </Button>
  );
}
