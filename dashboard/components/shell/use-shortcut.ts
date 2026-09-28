"use client";
import { useEffect } from "react";

function typing(e: KeyboardEvent) {
  const t = e.target as HTMLElement | null;
  return !!t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
}

/** A single-key shortcut, ignored while typing or with a modifier held. Keys are matched case-insensitively. */
export function useShortcut(key: string, run: () => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (typing(e) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key.toLowerCase() === key.toLowerCase()) { e.preventDefault(); run(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [key, run, enabled]);
}

/** G then a key (Linear style). `map` is second key -> action. The G window closes after 1s. */
export function useGoShortcuts(map: Record<string, () => void>) {
  useEffect(() => {
    let armed = 0;
    const onKey = (e: KeyboardEvent) => {
      if (typing(e) || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toUpperCase();
      if (k === "G") { armed = Date.now(); return; }
      if (armed && Date.now() - armed < 1000 && map[k]) {
        e.preventDefault();
        e.stopImmediatePropagation();
        map[k]();
      }
      armed = 0;
    };
    // capture, so a G-sequence wins over page single-key shortcuts
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [map]);
}
