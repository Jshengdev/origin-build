import { PageHeader } from "@/components/shell/page-header";
import { RoutinesLive } from "@/components/routines/routines-live";

/** Routines read and write the wtdd API (components/routines/routines-live.tsx): save the route by name, load it, run it. */
export default function RoutinesPage() {
  return (
    <>
      <PageHeader crumbs={[{ label: "Routines" }]} />
      <RoutinesLive />
    </>
  );
}
