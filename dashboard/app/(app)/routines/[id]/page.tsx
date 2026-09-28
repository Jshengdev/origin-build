import { redirect } from "next/navigation";

/** A routine has no page of its own: it is a row on /routines (load, run, save as). The mock editor stays in Storybook. */
export default function Page() {
  redirect("/routines");
}
