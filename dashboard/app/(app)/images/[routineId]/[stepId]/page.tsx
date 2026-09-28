import { AreaView } from "@/components/images/area-view";
import { SampleFrame } from "@/components/shell/sample-frame";

/** Back as a sample (Johnny, 17:3x: "bring them back so i can be more specific about what it should and shouldnt display"). Images are not wired yet. */
export default async function AreaPage({ params }: { params: Promise<{ routineId: string; stepId: string }> }) {
  const { routineId, stepId } = await params;
  return (
    <SampleFrame what="Images are not wired yet: no picture on this page is from the dog.">
      <AreaView routineId={routineId} stepId={stepId} />
    </SampleFrame>
  );
}
