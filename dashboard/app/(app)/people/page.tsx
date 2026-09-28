import { PageHeader } from "@/components/shell/page-header";
import { PeopleLive } from "@/components/people/people-live";

/** People reads GET /people (components/people/people-live.tsx): the group and its names, as served. */
export default function PeoplePage() {
  return (
    <>
      <PageHeader crumbs={[{ label: "People" }]} />
      <PeopleLive />
    </>
  );
}
