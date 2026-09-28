import { SessionDetail } from "@/components/sessions/sessions-view";
import { getDataSource, loadMap } from "@/lib/data";
import { SampleFrame } from "@/components/shell/sample-frame";

/** Back as a sample (Johnny, 17:3x: "bring them back so i can be more specific about what it should and shouldnt display"). Sessions are not wired yet. */
export default async function SessionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <SampleFrame what="Sessions are not wired yet: a run, its morning page, report and signature are on Record.">
      <SessionDetail id={Number(id)} map={await loadMap(getDataSource())} />
    </SampleFrame>
  );
}
