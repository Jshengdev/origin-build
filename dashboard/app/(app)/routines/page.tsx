import { RoutinesList } from "@/components/routines/routines-list";
import { SampleFrame } from "@/components/shell/sample-frame";
import { getDataSource, loadMap } from "@/lib/data";

/** Routines are not wired yet: shown as a sample (components/shell/sample-frame.tsx). Today a routine is the saved route, run as a morning or night run. */
export default async function RoutinesPage() {
  return (
    <SampleFrame what="Routines are not wired yet: today a routine is the route saved on Paths, run as a morning or night run from Record.">
      <RoutinesList map={await loadMap(getDataSource())} />
    </SampleFrame>
  );
}
