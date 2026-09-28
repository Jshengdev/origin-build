import { RoutineDetail } from "@/components/routines/routine-detail";
import { SampleFrame } from "@/components/shell/sample-frame";
import { getDataSource, loadMap } from "@/lib/data";

export default async function RoutinePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <SampleFrame what="Routines are not wired yet.">
      <RoutineDetail id={id} map={await loadMap(getDataSource())} />
    </SampleFrame>
  );
}
