"use client";
import { useState } from "react";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ActionButton, SelectMenu } from "@/components/wtdd";
import { HOME_ID, SAVED_PLACES, type Place } from "@/lib/mock/locations";
import { cn } from "@/lib/utils";

type Choice = "stay" | "home" | "place";

/** Confirm a stop, and say where the dog goes next: nowhere, home, or a saved place. */
export function StopDialog({ open, onOpenChange, what, onStop }: {
  open: boolean; onOpenChange: (o: boolean) => void; what: "routine" | "driving"; onStop: (dest?: Place) => void;
}) {
  const [choice, setChoice] = useState<Choice>("home");
  const others = SAVED_PLACES.filter((p) => p.id !== HOME_ID);
  const [placeId, setPlaceId] = useState(others[0].id);

  const confirm = () => {
    const dest = choice === "home" ? SAVED_PLACES.find((p) => p.id === HOME_ID) : choice === "place" ? SAVED_PLACES.find((p) => p.id === placeId) : undefined;
    onStop(dest);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle className="text-[17px]">{what === "routine" ? "Stop the routine?" : "Stop driving?"}</DialogTitle>
          <DialogDescription className="text-[15px] leading-[22px]">Then, where should the dog go?</DialogDescription>
        </DialogHeader>
        <div role="radiogroup" aria-label="Where the dog goes" className="flex flex-col gap-2">
          <Option choice={choice} onPick={setChoice} value="home" title="Return home" detail="Walk back to the home dock." />
          <Option choice={choice} onPick={setChoice} value="place" title="Go to a saved location" detail="Pick one of the places you saved.">
            {choice === "place" && (
              <div className="pl-6.5" onClick={(e) => e.stopPropagation()}>
                <Select value={placeId} onValueChange={setPlaceId}>
                  <SelectTrigger aria-label="Saved location" className="h-8 w-full border-input bg-card text-[13px] shadow-none"><SelectValue /></SelectTrigger>
                  <SelectMenu>{others.map((p) => <SelectItem key={p.id} value={p.id} className="text-[13px]">{p.name}</SelectItem>)}</SelectMenu>
                </Select>
              </div>
            )}
          </Option>
          <Option choice={choice} onPick={setChoice} value="stay" title="Stop where it is" detail="The dog sits and waits in place." />
        </div>
        <DialogFooter>
          <DialogClose asChild><ActionButton intent="secondary">{what === "routine" ? "Keep running" : "Keep driving"}</ActionButton></DialogClose>
          <ActionButton intent="primary" onClick={confirm}>{what === "routine" ? "Stop routine" : "Stop driving"}</ActionButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Option({ choice, onPick, value, title, detail, children }: {
  choice: Choice; onPick: (c: Choice) => void; value: Choice; title: string; detail: string; children?: React.ReactNode;
}) {
  return (
    <div
      role="radio"
      aria-checked={choice === value}
      tabIndex={0}
      onClick={() => onPick(value)}
      onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); onPick(value); } }}
      className={cn(
        "flex cursor-pointer flex-col gap-2 rounded-md border px-3 py-2.5 outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring",
        choice === value ? "border-foreground bg-accent" : "border-input hover:bg-accent",
      )}
    >
      <span className="flex items-center gap-2.5">
        <span aria-hidden className={cn("flex size-4 items-center justify-center rounded-full border", choice === value ? "border-foreground" : "border-input")}>
          {choice === value && <span className="size-2 rounded-full bg-foreground" />}
        </span>
        <span className="flex flex-col">
          <span className="text-[13px] font-medium">{title}</span>
          <span className="text-[13px] text-muted-foreground">{detail}</span>
        </span>
      </span>
      {children}
    </div>
  );
}
