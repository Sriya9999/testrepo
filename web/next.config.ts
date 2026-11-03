import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@marketingos/api-client"],
  output: "standalone",
  poweredByHeader: false,
};

export default config;
