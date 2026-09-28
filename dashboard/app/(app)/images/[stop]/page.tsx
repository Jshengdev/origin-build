import { notFound } from "next/navigation";
import { PageHeader } from "@/components/shell/page-header";
import { CompareStop } from "@/components/images/images-live";

/** /images/<stop>: the same map stop (a path index) across runs (components/images/images-live.tsx). */
export default async function CompareStopPage({ params }: { params: Promise<{ stop: string }> }) {
  const { stop } = await params;
  if (!/^\d+$/.test(stop)) notFound();
  return (
    <>
      <PageHeader crumbs={[{ label: "Images", href: "/images" }, { label: `Stop at dot ${Number(stop) + 1}` }]} />
      <CompareStop stop={Number(stop)} />
    </>
  );
}
