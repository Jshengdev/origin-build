import { PageHeader } from "@/components/shell/page-header";
import { OverviewLive } from "@/components/overview/overview-live";

/** Overview reads the wtdd API (see components/overview/overview-live.tsx); the fixture version stays in Storybook. */
export default function OverviewPage() {
  return (
    <>
      <PageHeader crumbs={[{ label: "Overview" }]} />
      <OverviewLive />
    </>
  );
}
