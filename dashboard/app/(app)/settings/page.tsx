import { PageHeader } from "@/components/shell/page-header";
import { MonitoringLive } from "@/components/settings/monitoring-live";

/** Settings is Monitoring, live (components/settings/monitoring-live.tsx): the integrations and the dog, as served. The
 *  theme switch is in the top bar; the mock site and appearance settings stay in Storybook. */
export default function SettingsPage() {
  return (
    <>
      <PageHeader crumbs={[{ label: "Settings" }]} />
      <MonitoringLive />
    </>
  );
}
