import { RoutineEditor } from "@/components/routines/routine-editor";
import { SampleFrame } from "@/components/shell/sample-frame";
import { getDataSource, loadMap } from "@/lib/data";

export default async function NewRoutinePage() {
  return (
    <SampleFrame what="Routines are not wired yet.">
      <RoutineEditor map={await loadMap(getDataSource())} />
    </SampleFrame>
  );
}
