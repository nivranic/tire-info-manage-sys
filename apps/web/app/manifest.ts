import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/", name: "胎迹 · 轮胎情报工作台", short_name: "胎迹", lang: "zh-CN",
    description: "在线核验精确轮胎规格，追溯每一项参数的原始证据。",
    start_url: "/", scope: "/", display: "standalone",
    background_color: "#f6f5f1", theme_color: "#f6f5f1",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
    ],
  };
}
