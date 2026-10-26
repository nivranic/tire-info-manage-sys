export const THEME_STORAGE_KEY = "tire-theme-v1";

export type ThemePreference = "system" | "light" | "dark" | "high-contrast";
export type ThemePalette = "light" | "dark" | "high-contrast";
export type NativeBrightness = "light" | "dark";

export interface ThemeAppearance {
  preference: ThemePreference;
  palette: ThemePalette;
  nativeBrightness: NativeBrightness;
}

export type ThemeChangeHandler = (brightness: NativeBrightness) => void;

export function parseThemePreference(raw: unknown): ThemePreference {
  return raw === "light" || raw === "dark" || raw === "high-contrast" || raw === "system"
    ? raw : "system";
}

export function resolveThemeAppearance(
  preference: ThemePreference,
  systemDark: boolean,
): ThemeAppearance {
  const palette: ThemePalette = preference === "system"
    ? (systemDark ? "dark" : "light") : preference;
  return { preference, palette, nativeBrightness: palette === "light" ? "light" : "dark" };
}
