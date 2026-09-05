import type { NextConfig } from "next";

const API_ORIGIN = process.env.API_PROXY_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Next dev mode blocks cross-origin requests for its own dev assets (HMR)
  // by default. nginx (OMNI-111) proxies with the original Host header
  // (127.0.0.1/localhost), which looks cross-origin to the dev server
  // otherwise sitting on :3000 — allow both loopback forms through.
  allowedDevOrigins: ["localhost", "127.0.0.1"],

  // The frontend calls the API with relative paths (see src/lib/api-client.ts)
  // so requests stay same-origin — required once nginx (OMNI-111) terminates
  // TLS in front of both: a same-origin call rides the encrypted connection
  // the browser already has, instead of reaching out to the backend's own
  // plaintext dev port directly. This rewrite is what makes relative paths
  // work when running `npm run dev` directly (bypassing nginx) too.
  async rewrites() {
    return [
      { source: "/auth/:path*", destination: `${API_ORIGIN}/auth/:path*` },
      { source: "/admin/:path*", destination: `${API_ORIGIN}/admin/:path*` },
      { source: "/nav", destination: `${API_ORIGIN}/nav` },
      { source: "/health", destination: `${API_ORIGIN}/health` },
      { source: "/docs", destination: `${API_ORIGIN}/docs` },
      { source: "/openapi.json", destination: `${API_ORIGIN}/openapi.json` },
      { source: "/redoc", destination: `${API_ORIGIN}/redoc` },
    ];
  },
};

export default nextConfig;
