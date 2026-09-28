/**
 * Mock image history. Each image is a generated SVG, labeled "fixture, not a photo", with a visible change from
 * night to night so the compare view has something to compare. Replace with /pictures/ and look rows.
 */
import type { Routine } from "./routines";

export interface AreaImage { id: string; routineId: string; stepId: string; takenAt: string; image: string }
export interface Capture { id: string; takenAt: string; sessionId: number; near: string; image: string }

const DAYS = ["2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26"];

/** A placeholder scene. `progress` 0..1 grows a stack of boxes and a painted strip, so two dates differ. */
export function sceneSvg(label: string, date: string, progress: number, seed = 0) {
  const w = 640, h = 400;
  const boxes = Math.round(1 + progress * 5);
  const paint = Math.round(80 + progress * 400);
  const shift = (seed * 37) % 120;
  const stack = Array.from({ length: boxes }, (_, i) =>
    `<rect x="${360 + (i % 3) * 58}" y="${250 - Math.floor(i / 3) * 44}" width="54" height="40" rx="3" fill="#B8B8AE"/>`).join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">
<rect width="${w}" height="${h}" fill="#E9E9E3"/><rect y="290" width="${w}" height="110" fill="#D2D2CA"/>
<rect x="${40 + shift}" y="110" width="160" height="180" rx="6" fill="#C9C9C0"/>
<rect x="40" y="70" width="${paint}" height="14" rx="2" fill="#9FA89A"/>
${stack}
<text x="20" y="36" font-family="Instrument Sans, sans-serif" font-size="14" fill="#A5342A">fixture, not a photo</text>
<text x="20" y="380" font-family="Instrument Sans, sans-serif" font-size="14" fill="#5C5D58">${label} · ${date}</text></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

/** A week of nightly images for each step of the given routines. */
export function seedHistory(routines: Routine[]): AreaImage[] {
  return routines.flatMap((r, ri) =>
    r.steps.flatMap((st, si) =>
      DAYS.map((d, di) => ({
        id: `${r.id}:${st.id}:${d}`,
        routineId: r.id,
        stepId: st.id,
        takenAt: `${d}T${ri ? "16:3" : "23:0"}${si}:00Z`,
        image: sceneSvg(st.name, d, di / (DAYS.length - 1), si + ri),
      })),
    ),
  );
}

export const INITIAL_CAPTURES: Capture[] = [
  { id: "c1", takenAt: "2026-09-25T19:14:00Z", sessionId: 13, near: "Garage door", image: sceneSvg("Garage door", "2026-09-25", 0.3, 4) },
  { id: "c2", takenAt: "2026-09-25T19:18:00Z", sessionId: 13, near: "Side yard", image: sceneSvg("Side yard", "2026-09-25", 0.6, 5) },
  { id: "c3", takenAt: "2026-09-22T18:02:00Z", sessionId: 10, near: "Back wall", image: sceneSvg("Back wall", "2026-09-22", 0.2, 6) },
];
