"use client";
import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ActionButton, SignalChip } from "@/components/wtdd";
import { usePageHeaderSlots } from "./page-header";

/** The head's law audit: on any API but the live one (:7788), the top bar says so, so a dry API's fixtures never pass for
 *  the dog. On the live API it says nothing (Johnny: no dev tags on camera). A failed read of the target says FAILED. */
function ApiChip() {
  const [t, setT] = useState<{ api?: string; error?: string }>({});
  useEffect(() => {
    fetch("/api/target").then((r) => r.json()).then((j) => setT(typeof j?.api === "string" ? { api: j.api } : { error: "no api served" })).catch((e) => setT({ error: String(e) }));
  }, []);
  if (t.error) return <SignalChip tone="alert">API · FAILED to read which one</SignalChip>;
  if (!t.api) return null;
  const port = t.api.match(/:(\d+)\/?$/)?.[1] ?? t.api;
  return port === "7788" ? null : <SignalChip tone="neutral">dry API :{port} · no dog</SignalChip>;
}

export function TopBar() {
  const { resolvedTheme, setTheme } = useTheme();
  const { setCrumbs } = usePageHeaderSlots();
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4">
      <SidebarTrigger className="-ml-1 text-muted-foreground" />
      <div ref={setCrumbs} className="min-w-0 flex-1" />
      <ApiChip />
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
