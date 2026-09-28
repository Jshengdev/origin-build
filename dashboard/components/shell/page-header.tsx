"use client";
import Link from "next/link";
import { createContext, Fragment, useContext, useState } from "react";
import { createPortal } from "react-dom";
import {
  Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";

/**
 * The top bar holds the page name and breadcrumb only. Pages fill it with <PageHeader>, portaled, so no state
 * round-trips. Actions never go in the top bar: they belong in the page (see PageActions).
 */
interface Slots { crumbs: HTMLElement | null; setCrumbs: (el: HTMLElement | null) => void }
const Ctx = createContext<Slots | null>(null);

export function PageHeaderSlots({ children }: { children: React.ReactNode }) {
  const [crumbs, setCrumbs] = useState<HTMLElement | null>(null);
  return <Ctx.Provider value={{ crumbs, setCrumbs }}>{children}</Ctx.Provider>;
}
export const usePageHeaderSlots = () => useContext(Ctx)!;

export interface Crumb { label: string; href?: string }

export function PageHeader({ crumbs }: { crumbs: Crumb[] }) {
  const slots = useContext(Ctx);
  if (!slots?.crumbs) return null;
  return createPortal(
        <Breadcrumb>
          <BreadcrumbList className="text-[15px]">
            {crumbs.map((c, i) => (
              <Fragment key={i}>
                {i > 0 && <BreadcrumbSeparator />}
                <BreadcrumbItem>
                  {c.href && i < crumbs.length - 1
                    ? <BreadcrumbLink asChild><Link href={c.href}>{c.label}</Link></BreadcrumbLink>
                    : <BreadcrumbPage className="font-semibold">{c.label}</BreadcrumbPage>}
                </BreadcrumbItem>
              </Fragment>
            ))}
          </BreadcrumbList>
        </Breadcrumb>,
    slots.crumbs,
  );
}

/** A page's key actions, at the top of the page content. At least a button's height, so a page with only chips starts its
 * first module where every other page does and switching tabs does not make the content hop. */
export function PageActions({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={`flex min-h-9 flex-wrap items-center gap-2 ${className ?? ""}`}>{children}</div>;
}
