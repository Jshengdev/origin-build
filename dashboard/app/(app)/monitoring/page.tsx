import { PageHeader } from "@/components/shell/page-header";
import { MonitoringView } from "@/components/monitoring/monitoring-view";
import { SampleFrame } from "@/components/shell/sample-frame";
import { getDataSource } from "@/lib/data";

/** Back as a sample (Johnny, 17:3x: "bring them back so i can be more specific about what it should and shouldnt display"). Monitoring is not wired yet. */
export default async function MonitoringPage() {
  const ds = getDataSource();
  const [devices, evals] = await Promise.all([ds.getDevices(), ds.getEvals()]);
  return (
    <>
      <PageHeader crumbs={[{ label: "Monitoring" }]} />
      <SampleFrame what="Monitoring is not wired yet: the dog's real health is on Overview's Body card.">
        <MonitoringView devices={devices} evals={evals} />
      </SampleFrame>
    </>
  );
}
