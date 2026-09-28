import { PageHeader } from "@/components/shell/page-header";
import { ImagesLive } from "@/components/images/images-live";

/** Images reads GET /sessions and GET /images (components/images/images-live.tsx): a run's photos, by stop. */
export default function ImagesPage() {
  return (
    <>
      <PageHeader crumbs={[{ label: "Images" }]} />
      <ImagesLive />
    </>
  );
}
