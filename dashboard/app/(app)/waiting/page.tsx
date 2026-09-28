import { PageHeader } from "@/components/shell/page-header";
import { WaitingLive } from "@/components/waiting/waiting-live";

/** Waiting reads the ledger (components/waiting/waiting-live.tsx): the dog's asks to the group and the answers. */
export default function WaitingPage() {
  return (
    <>
      <PageHeader crumbs={[{ label: "Waiting" }]} />
      <WaitingLive />
    </>
  );
}
