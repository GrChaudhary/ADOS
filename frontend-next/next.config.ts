import type { NextConfig } from "next";

const BACKEND_ORIGIN = process.env.ADOS_BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Emits .next/standalone with only the traced runtime dependencies, so the
  // production image doesn't have to carry the full node_modules tree. Used
  // by frontend-next/Dockerfile; harmless for `next dev`.
  output: "standalone",

  async rewrites() {
    // Proxies fetch() calls to the real FastAPI backend so the browser
    // never needs CORS for plain requests. The SSE EventSource connection
    // (frontend-next/src/lib/api.ts) can't go through this proxy reliably
    // for a long-lived stream, so it connects to BACKEND_ORIGIN directly -
    // that's why backend/app/main.py's CORSMiddleware is still required.
    return [
      {
        source: "/api/backend/:path*",
        destination: `${BACKEND_ORIGIN}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
