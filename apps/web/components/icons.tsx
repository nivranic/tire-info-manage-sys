import type { CSSProperties } from "react";

export type IconName = "search" | "vehicle" | "compare" | "bookmark" | "source" | "arrow" | "close" | "sun" | "moon" | "check" | "external" | "refresh" | "shield" | "file" | "chevron";
const paths: Record<IconName, React.ReactNode> = {
  search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4.5 4.5" /></>,
  vehicle: <><path d="m5 10 2-5h10l2 5M3 11l2-1h14l2 1v7H3v-7Zm2 7v2m14-2v2M6 14h2m8 0h2" /></>,
  compare: <><path d="M8 4v16M16 4v16M3 8h10M11 16h10" /><circle cx="8" cy="8" r="2" /><circle cx="16" cy="16" r="2" /></>,
  bookmark: <path d="M6 4h12v17l-6-4-6 4V4Z" />,
  source: <><path d="M4 5h16v14H4zM4 9h16M9 9v10" /><path d="M6.5 7h.01M9 7h.01" /></>,
  arrow: <path d="M4 12h15m-6-6 6 6-6 6" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>,
  moon: <path d="M20 14.2A8.8 8.8 0 0 1 9.8 4 8.8 8.8 0 1 0 20 14.2Z" />,
  check: <path d="m5 12 4 4L19 6" />,
  external: <><path d="M14 4h6v6m0-6L10 14" /><path d="M10 4H4v16h16v-6" /></>,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6 7a7 7 0 0 1 11-1l3 6M4 12l3 6a7 7 0 0 0 11-1" /></>,
  shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z" /><path d="m8 12 3 3 5-6" /></>,
  file: <><path d="M13 3H5v18h14V9l-6-6Z" /><path d="M13 3v6h6M8 13h8M8 17h6" /></>,
  chevron: <path d="m9 5 7 7-7 7" />,
};

export function Icon({ name, size = 20, className, style }: { name: IconName; size?: number; className?: string; style?: CSSProperties }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={className} style={style}>{paths[name]}</svg>;
}
