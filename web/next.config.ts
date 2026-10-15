import type { NextConfig } from "next";

// IDDAA_STATIC_DIR verilirse statik site (GitHub Pages) olarak dışa aktarılır; aksi halde yerel canlı mod.
const isStatic = Boolean(process.env.IDDAA_STATIC_DIR);
const basePath = process.env.NEXT_BASE_PATH ?? "";

const nextConfig: NextConfig = {
  // PPR/Cache Components statik dışa aktarmayla uyumsuz; statik modda her şey zaten derleme anında üretilir
  cacheComponents: !isStatic,
  partialPrefetching: !isStatic,
  ...(isStatic ? { output: "export" as const, trailingSlash: true, basePath, images: { unoptimized: true } } : {}),
  env: {
    NEXT_PUBLIC_STATIC_MODE: isStatic ? "1" : "",
    NEXT_PUBLIC_REPO_URL: process.env.NEXT_PUBLIC_REPO_URL ?? "",
  },
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
