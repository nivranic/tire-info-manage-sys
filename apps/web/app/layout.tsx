import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "胎迹 · 轮胎情报工作台",
  description: "从精确规格到原始证据。在线核验轮胎参数，明确区分实时来源与历史快照。",
  appleWebApp: { capable: true, title: "胎迹", statusBarStyle: "default" },
  icons: { apple: "/icons/icon-180.png" },
};

export const viewport: Viewport = { themeColor: "#f6f5f1" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
