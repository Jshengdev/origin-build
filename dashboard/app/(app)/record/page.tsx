import { PageHeader } from "@/components/shell/page-header";
import { RecordLive } from "@/components/record/record-live";

/** Record reads the wtdd API (components/record/record-live.tsx): the spec's third-wow page the app did not have. */
export default function RecordPage() {
  return (
    <>
      <PageHeader crumbs={[{ label: "Record" }]} />
      <RecordLive />
    </>
  );
}
