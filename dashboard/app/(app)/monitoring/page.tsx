import { redirect } from "next/navigation";

/** Monitoring lives in Settings now (Johnny: "let's get monitoring live and put that into settings"). */
export default function Page() {
  redirect("/settings");
}
