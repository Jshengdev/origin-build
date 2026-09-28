import { redirect } from "next/navigation";

/** The photos live where they were taken now: a run's looks on Routines, an ask's photo on Waiting (GET /images, #73). */
export default function Page() {
  redirect("/routines");
}
