import path from "node:path";
import type { NextConfig } from "next";

// The shared API client lives in ../packages, so the build root is the monorepo root.
const root = path.join(__dirname, "..");
// When set at build time, the web server proxies the API, so the browser talks to one origin.
const apiInternalUrl = process.env.API_INTERNAL_URL?.replace(/\/$/, "");

const config: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@marketingos/api-client"],
  output: "standalone",
  outputFileTracingRoot: root,
  turbopack: { root },
  poweredByHeader: false,
  async rewrites() {
    if (!apiInternalUrl) return [];
    return [
      { source: "/api/v1/:path*", destination: `${apiInternalUrl}/api/v1/:path*` },
      { source: "/media/:path*", destination: `${apiInternalUrl}/media/:path*` },
    ];
  },
};

export default config;
