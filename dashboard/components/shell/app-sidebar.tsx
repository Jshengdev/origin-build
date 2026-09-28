"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo } from "react";
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem,
} from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import { NAV, SAMPLES, SETTINGS, type NavEntry } from "./nav";
import { useGoShortcuts } from "./use-shortcut";
import { openAsks, useAsks } from "@/components/waiting/waiting-live";
import { redact } from "@/lib/data/api";

function NavItem({ entry, active, dot, count, failed }: { entry: NavEntry; active: boolean; dot?: boolean; count?: number; failed?: string }) {
  const Icon = entry.icon;
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        asChild
        isActive={active}
        tooltip={entry.label}
        className={cn(
          "h-8 text-[13px] font-medium text-muted-foreground border border-transparent",
          "data-[active=true]:border-border data-[active=true]:text-foreground",
        )}
      >
        <Link href={entry.href}>
          <Icon strokeWidth={1.5} />
          {/* One line that clips while the sidebar animates open; no wrap, no ellipsis. */}
          <span className="overflow-hidden whitespace-nowrap text-clip!">{entry.label}</span>
          {dot && <span aria-label="live" className="ml-auto size-4 shrink-0 rounded-[2px] bg-signal-good group-data-[collapsible=icon]:hidden" />}
          {failed ? (   // the read behind the count failed: say so where the count would be, never an empty slot
            <span title={failed} aria-label={`${entry.label} count FAILED: ${failed}`} className="ml-auto flex h-4 shrink-0 items-center rounded-[2px] bg-signal-alert-soft px-1 text-[11px] font-medium text-signal-alert group-data-[collapsible=icon]:hidden">
              FAILED
            </span>
          ) : !!count && (
            <span aria-label={`${count} waiting`} className="ml-auto flex h-4 min-w-4 shrink-0 items-center justify-center rounded-[2px] bg-highlight px-1 text-[11px] font-medium text-on-highlight group-data-[collapsible=icon]:hidden">
              {count}
            </span>
          )}
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

export function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  const go = useMemo(
    () => Object.fromEntries([...NAV, ...SAMPLES, SETTINGS].map((e) => [e.key, () => router.push(e.href)])),
    [router],
  );
  useGoShortcuts(go);
  const asks = useAsks(), waiting = openAsks(asks);   // the one highlight in the shell: asks no one has answered yet (GET /ledger, every 3 s)
  const failed = asks.ledger.error ? redact(asks.ledger.error) : undefined;

  return (
    <Sidebar collapsible="icon" className="border-r border-sidebar-border">
      <SidebarHeader className="gap-3 px-3 pt-4 pb-5">
        <div className="overflow-hidden whitespace-nowrap px-1 text-[13px] font-semibold leading-[18px] group-data-[collapsible=icon]:hidden">What the Dog Doin</div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup className="px-3">
          <SidebarMenu className="gap-1">
            {/* Waiting's count is read from the ledger, as Waiting reads it. The live dot stays off until Live reads the API, so
                no fixture state sits in the shell unbadged. */}
            {NAV.map((e) => <NavItem key={e.href} entry={e} active={isActive(e.href)} count={e.href === "/waiting" ? waiting : undefined} failed={e.href === "/waiting" ? failed : undefined} />)}
          </SidebarMenu>
        </SidebarGroup>
        <SidebarGroup className="px-3">
          <SidebarGroupLabel>Samples · not live yet</SidebarGroupLabel>
          <SidebarMenu className="gap-1">
            {SAMPLES.map((e) => <NavItem key={e.href} entry={e} active={isActive(e.href)} />)}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="px-3 pb-4">
        <SidebarMenu>
          <NavItem entry={SETTINGS} active={isActive(SETTINGS.href)} />
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
