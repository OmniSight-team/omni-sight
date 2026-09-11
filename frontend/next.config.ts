import type { NextConfig } from "next";

const API_ORIGIN = process.env.API_PROXY_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Next dev mode blocks cross-origin requests for its own dev assets (HMR)
  // by default. nginx (OMNI-111) proxies with the original Host header
  // (127.0.0.1/localhost), which looks cross-origin to the dev server
  // otherwise sitting on :3000 — allow both loopback forms through.
  allowedDevOrigins: ["localhost", "127.0.0.1"],

  // The frontend calls the API with relative /api/* paths (see
  // src/lib/api-client.ts) so requests stay same-origin — required once
  // nginx (OMNI-111) terminates TLS in front of both: a same-origin call
  // rides the encrypted connection the browser already has, instead of
  // reaching out to the backend's own plaintext dev port directly. This
  // rewrite is what makes /api/* work when running `npm run dev` directly
  // (bypassing nginx) too.
  //
  // The /api prefix (OMNI-208) exists because a resource path and a
  // frontend screen path can otherwise collide — /cameras is both the
  // camera-list endpoint and the Cameras screen. Stripping /api here keeps
  // query's own routes exactly as every other ticket already built and
  // tested them; only this edge layer knows the prefix exists.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/:path*` }];
  },
};

export default nextConfig;
