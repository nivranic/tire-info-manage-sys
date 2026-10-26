"use client";

import { useId } from "react";
import { useThemePreferences } from "./theme-preferences";
import type { ThemePreference } from "./theme-preference-values";

const paletteLabels = { light: "浅色", dark: "深色", "high-contrast": "高对比度" };

export default function ThemePreferenceControl() {
  const id = useId();
  const { appearance, ready, setPreference } = useThemePreferences();
  const statusId = `${id}-status`;

  return <div className="theme-preference-control" data-theme-preference-control="">
    <label htmlFor={id}>主题</label>
    <select id={id} value={appearance.preference} aria-describedby={statusId}
      onChange={event => setPreference(event.target.value as ThemePreference)}>
      <option value="system">跟随系统</option>
      <option value="light">浅色</option>
      <option value="dark">深色</option>
      <option value="high-contrast">高对比度</option>
    </select>
    <span id={statusId} className="theme-preference-status">{ready ? `实际配色：${paletteLabels[appearance.palette]}` : "正在读取外观…"}</span>
  </div>;
}
