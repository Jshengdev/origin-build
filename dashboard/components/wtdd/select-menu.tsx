"use client";
import { useCallback } from "react";
import { SelectContent } from "@/components/ui/select";   // stock shadcn, never edited
import { cn } from "@/lib/utils";

/**
 * Dropdown list for stock shadcn <Select>: always opens below the trigger (never over it), and scrolls so the
 * selected option sits at the top of the list; the rest scroll above and below it.
 */
export function SelectMenu({ className, children, ...props }: React.ComponentProps<typeof SelectContent>) {
  const pinSelected = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    // After Radix focuses the selected item on open, move it to the top of the viewport.
    const pin = () => {
      const viewport = node.querySelector<HTMLElement>("[data-radix-select-viewport]");
      const checked = node.querySelector<HTMLElement>("[data-state=checked]");
      if (!viewport || !checked) return;
      const target = viewport.scrollTop + checked.getBoundingClientRect().top - viewport.getBoundingClientRect().top - 4;
      const maxScroll = viewport.scrollHeight - viewport.clientHeight;
      // Room below the last option so even a late option can scroll to the top of the capped list.
      if (target > maxScroll) viewport.style.paddingBottom = `${(parseFloat(viewport.style.paddingBottom) || 0) + target - maxScroll}px`;
      viewport.scrollTop = target;
    };
    // After Radix focuses the selected item on open (and again once the padding has grown the list).
    requestAnimationFrame(() => { pin(); setTimeout(pin, 40); });
  }, []);

  return (
    <SelectContent
      ref={pinSelected}
      position="popper"
      side="bottom"
      align="start"
      sideOffset={4}
      avoidCollisions={false}
      className={cn("max-h-56", className)}
      {...props}
    >
      {children}
    </SelectContent>
  );
}
