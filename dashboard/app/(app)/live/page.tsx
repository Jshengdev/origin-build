import { LiveView } from "@/components/live/live-view";
import { getDataSource, loadMap } from "@/lib/data";
import { SampleFrame } from "@/components/shell/sample-frame";

/** Back as a sample (Johnny, 17:3x: "bring them back so i can be more specific about what it should and shouldnt display"). The live view is not wired here. */
export default async function LivePage() {
  return (
    <SampleFrame what="The live view is not wired here: the dog's camera and its live map are on Overview.">
      <LiveView map={await loadMap(getDataSource())} />
    </SampleFrame>
  );
}
