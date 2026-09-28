import type { Route, Stop } from "@/lib/data";
import type { Routine, RoutineStep } from "./routines";

/** A routine drawn on the TwinMap: its points as numbered stops, joined in order. */
export function stepsAsStops(steps: RoutineStep[]): Stop[] {
  return steps.map((st, i) => ({ id: st.id, index: i + 1, name: st.name, position: st.position, look: "nod" }));
}

export function routineAsRoute(r: Pick<Routine, "id" | "name" | "steps">): Route[] {
  if (r.steps.length < 2) return [];
  return [{ id: r.id, name: r.name, source: "routine", status: "exists_on_main", polyline: r.steps.map((s) => s.position) }];
}
