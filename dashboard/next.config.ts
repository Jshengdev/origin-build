import type { NextConfig } from "next";

/** /api/* is proxied per request by app/api/[...path]/route.ts, which reads WTDD_API at run time (the live day's one switch). */
const nextConfig: NextConfig = {
  // The dev badge sits on top of the sidebar's Settings item.
  devIndicators: false,
};

export default nextConfig;
