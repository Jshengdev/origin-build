import { PageHeader } from "@/components/shell/page-header";
import { PathsLive } from "@/components/paths/paths-live";

/** Paths reads and writes the wtdd API (components/paths/paths-live.tsx): the spec's page the app did not have. */
export default function PathsPage() {
  return (
    <>
      <PageHeader crumbs={[{ label: "Paths" }]} />
      <PathsLive />
    </>
  );
}
