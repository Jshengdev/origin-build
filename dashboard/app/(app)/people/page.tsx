import { PeopleView } from "@/components/people/people-view";
import { SampleFrame } from "@/components/shell/sample-frame";

/** Back as a sample (Johnny, 17:3x: "bring them back so i can be more specific about what it should and shouldnt display"). People are not wired yet. */
export default function PeoplePage() {
  return (
    <SampleFrame what="People are not wired yet: the group's real asks and answers are on Waiting.">
      <PeopleView />
    </SampleFrame>
  );
}
