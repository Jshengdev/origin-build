"use client";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ActionButton } from "@/components/wtdd";
import { usePageHeaderSlots } from "./page-header";

export function TopBar() {
  const { resolvedTheme, setTheme } = useTheme();
  const { setCrumbs } = usePageHeaderSlots();
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4">
      <SidebarTrigger className="-ml-1 text-muted-foreground" />
      <div ref={setCrumbs} className="min-w-0 flex-1" />
      <ActionButton
        intent="quiet"
        size="icon"
        aria-label="Toggle theme"
        onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      >
        <Sun className="hidden dark:block" strokeWidth={1.5} />
        <Moon className="dark:hidden" strokeWidth={1.5} />
      </ActionButton>
    </header>
  );
}
