/**
 * The one switch for the live day, read on EVERY request (not at build time): /api/* goes to the wtdd API
 * (origin-build's wtdd/api.py), same origin for the browser. Unset, it is the dry API on 7960 (a worktree of
 * origin-build main, which can never reach the dog). Only for the live session or filming does Johnny start this app with
 * WTDD_API=http://127.0.0.1:7788, the API that holds the dog; a restart with it unset goes back to dry.
 *
 * An API that does not answer is a 502 naming the address and the cause (connection refused, ...), never the generic
 * 500 a rewrite gives, so the page's FAILED line says what actually happened.
 */
import { apiTarget as api } from "@/lib/data/api-target";

async function proxy(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const target = `${api()}/${path.map(encodeURIComponent).join("/")}${new URL(req.url).search}`;
  try {
    const res = await fetch(target, {
      method: req.method,
      headers: { "Content-Type": req.headers.get("content-type") ?? "application/json" },
      body: req.method === "POST" ? await req.arrayBuffer() : undefined,
      cache: "no-store",
    });
    return new Response(res.body, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("content-type") ?? "application/octet-stream", "Cache-Control": "no-store" },
    });
  } catch (e) {
    const cause = e instanceof Error ? (e.cause instanceof Error ? e.cause.message : e.message) : String(e);
    return Response.json({ ok: false, error: `the wtdd API at ${api()} did not answer: ${cause}` }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST };
