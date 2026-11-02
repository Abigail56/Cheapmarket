import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Dev only: without this, opening the shop by IP (a phone on the same Wi-Fi, or 127.0.0.1)
  // gets no working JavaScript from the dev server, so no button responds.
  allowedDevOrigins: ["127.0.0.1", "192.168.*.*", "10.*.*.*", "172.*.*.*"],
  cacheComponents: true,
  partialPrefetching: true,
  // Self-contained server bundle for the Docker image (see Dockerfile)
  output: "standalone",
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
