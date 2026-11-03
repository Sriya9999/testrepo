import path from "node:path";
import type { NextConfig } from "next";

// The shared API client lives in ../packages, so the build root is the monorepo root.
const root = path.join(__dirname, "..");

const config: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@marketingos/api-client"],
  output: "standalone",
  outputFileTracingRoot: root,
  turbopack: { root },
  poweredByHeader: false,
};

export default config;
