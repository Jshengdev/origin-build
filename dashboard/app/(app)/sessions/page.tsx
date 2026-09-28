import { SessionsView } from "@/components/sessions/sessions-view";
import { SampleFrame } from "@/components/shell/sample-frame";

/** Back as a sample (Johnny, 17:3x: "bring them back so i can be more specific about what it should and shouldnt display"). Sessions are not wired yet. */
export default function SessionsPage() {
  return (
    <SampleFrame what="Sessions are not wired yet: a run, its morning page, report and signature are on Record.">
      <SessionsView />
    </SampleFrame>
  );
}
