import { DrivingView } from "@/components/driving/driving-view";
import { getDataSource, loadMap } from "@/lib/data";
import { SampleFrame } from "@/components/shell/sample-frame";

/** Back as a sample (Johnny, 17:3x: "bring them back so i can be more specific about what it should and shouldnt display"). Driving is not wired here. */
export default async function DrivingPage() {
  return (
    <SampleFrame what="Driving is not wired here: the drive switch (W A S D, Q E) and Stop are on Overview.">
      <DrivingView map={await loadMap(getDataSource())} />
    </SampleFrame>
  );
}
