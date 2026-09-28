import { apiTarget } from "@/lib/data/api-target";

/** GET /api/target: which wtdd API the proxy reads, so the top bar can say when it is not the live one (the head's law
 *  audit: a dry API's fixtures must never pass for the dog). The dashboard's own route; it never reaches the API. */
export function GET() {
  return Response.json({ api: apiTarget() });
}
