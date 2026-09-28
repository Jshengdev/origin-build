"use client";
import { useEffect, useState } from "react";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "./app-sidebar";
import { AppStateProvider } from "./app-state";
import { AsksProvider } from "@/components/waiting/waiting-live";
import { PageHeaderSlots } from "./page-header";
import { TopBar } from "./top-bar";

/** Sidebar is 232px and collapses to a 64px icon rail under 1024px (DESIGN_SYSTEM.md, Sidebar). */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(true);
  useEffect(() => {
    const mql = window.matchMedia("(max-width: 1023px)");
    const sync = () => setOpen(!mql.matches);
    sync();
    mql.addEventListener("change", sync);
    return () => mql.removeEventListener("change", sync);
  }, []);

  return (
    <AppStateProvider>
    <PageHeaderSlots>
    <AsksProvider>
    <SidebarProvider
      open={open}
      onOpenChange={setOpen}
      style={{ "--sidebar-width": "232px", "--sidebar-width-icon": "64px" } as React.CSSProperties}
    >
      <AppSidebar />
      <SidebarInset className="min-w-0 bg-background">
        <TopBar />
        <div className="flex flex-col gap-4 p-4 lg:p-8">
          {children}
        </div>
      </SidebarInset>
    </SidebarProvider>
    </AsksProvider>
    </PageHeaderSlots>
    </AppStateProvider>
  );
}
