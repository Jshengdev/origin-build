import { redirect } from "next/navigation";

/** Sessions live in Record now: every run in one table, and a row opens its record (GET /sessions, #75). */
export default function Page() {
  redirect("/record");
}
