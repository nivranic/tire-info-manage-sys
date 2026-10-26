"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { parseThemePreference, resolveThemeAppearance, THEME_STORAGE_KEY } from "./theme-preference-values";
import type { NativeBrightness, ThemeAppearance, ThemeChangeHandler, ThemePreference } from "./theme-preference-values";

interface ThemePreferences {
  appearance: ThemeAppearance;
  ready: boolean;
  setPreference: (next: ThemePreference) => void;
}

interface ThemeProviderProps {
  children: ReactNode;
  onThemeChange?: ThemeChangeHandler;
}

interface ThemeState {
  appearance: ThemeAppearance;
  ready: boolean;
}

interface OwnedAttribute {
  previous: string | null;
  written: string | null;
}

interface RootThemeOwnership {
  root: HTMLElement;
  theme: OwnedAttribute;
  preference: OwnedAttribute;
  colorScheme: OwnedAttribute & { previousPriority: string };
}

const ThemePreferencesContext = createContext<ThemePreferences | null>(null);
const SYSTEM_DARK_QUERY = "(prefers-color-scheme: dark)";

function readStoredPreference(): ThemePreference {
  try {
    return parseThemePreference(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "system";
  }
}

function readSystemMedia(): MediaQueryList | null {
  try {
    return typeof window.matchMedia === "function" ? window.matchMedia(SYSTEM_DARK_QUERY) : null;
  } catch {
    return null;
  }
}

function isSystemDark(media: MediaQueryList | null): boolean {
  try {
    return media?.matches === true;
  } catch {
    return false;
  }
}

function writeOwnedAttribute(root: HTMLElement, name: string, ownership: OwnedAttribute, value: string) {
  const current = root.getAttribute(name);
  if (ownership.written !== null && current !== ownership.written) ownership.previous = current;
  root.setAttribute(name, value);
  ownership.written = value;
}

function restoreRootTheme(ownership: RootThemeOwnership) {
  const { root } = ownership;
  for (const [name, attribute] of [
    ["data-theme", ownership.theme], ["data-theme-preference", ownership.preference],
  ] as const) {
    if (attribute.written === null || root.getAttribute(name) !== attribute.written) continue;
    if (attribute.previous === null) root.removeAttribute(name);
    else root.setAttribute(name, attribute.previous);
  }
  const colorScheme = ownership.colorScheme;
  if (colorScheme.written !== null && root.style.getPropertyValue("color-scheme") === colorScheme.written
    && root.style.getPropertyPriority("color-scheme") === "") {
    if (colorScheme.previous) root.style.setProperty("color-scheme", colorScheme.previous, colorScheme.previousPriority);
    else root.style.removeProperty("color-scheme");
  }
}

export function ThemeProvider({ children, onThemeChange }: ThemeProviderProps) {
  // The server and first hydration render share this browser-independent placeholder.
  const [state, setState] = useState<ThemeState>(() => ({
    appearance: resolveThemeAppearance("system", false), ready: false,
  }));
  const stateRef = useRef(state);
  const mountedRef = useRef(true);
  const rootOwnershipRef = useRef<RootThemeOwnership | null>(null);
  const notifiedBrightnessRef = useRef<NativeBrightness | null>(null);

  const publishAppearance = useCallback((appearance: ThemeAppearance) => {
    if (!mountedRef.current) return;
    const current = stateRef.current;
    if (current.ready && current.appearance.preference === appearance.preference
      && current.appearance.palette === appearance.palette
      && current.appearance.nativeBrightness === appearance.nativeBrightness) return;
    const next = { appearance, ready: true };
    stateRef.current = next;
    setState(next);
  }, []);

  const setPreference = useCallback((next: ThemePreference) => {
    if (!mountedRef.current) return;
    const systemDark = next === "system" && isSystemDark(readSystemMedia());
    publishAppearance(resolveThemeAppearance(next, systemDark));
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // A storage failure does not roll back the user's in-memory selection.
    }
  }, [publishAppearance]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (rootOwnershipRef.current) restoreRootTheme(rootOwnershipRef.current);
      rootOwnershipRef.current = null;
    };
  }, []);

  useEffect(() => {
    let active = true;
    const preference = stateRef.current.ready ? stateRef.current.appearance.preference : readStoredPreference();
    const media = preference === "system" ? readSystemMedia() : null;
    const update = () => {
      if (!active || (stateRef.current.ready && stateRef.current.appearance.preference !== preference)) return;
      publishAppearance(resolveThemeAppearance(preference, isSystemDark(media)));
    };
    update();
    if (!media) return () => { active = false; };

    let removeListener: (() => void) | undefined;
    try {
      if (typeof media.addEventListener === "function" && typeof media.removeEventListener === "function") {
        media.addEventListener("change", update);
        removeListener = () => media.removeEventListener("change", update);
      } else if (typeof media.addListener === "function" && typeof media.removeListener === "function") {
        media.addListener(update);
        removeListener = () => media.removeListener(update);
      }
    } catch {
      // Some embedded hosts expose matchMedia without usable listener methods.
    }
    // Re-read the same MediaQueryList after subscribing to close the initial-read gap.
    update();
    return () => {
      active = false;
      try { removeListener?.(); } catch { /* The detached host may already be unavailable. */ }
    };
  }, [state.appearance.preference, publishAppearance]);

  useEffect(() => {
    if (!state.ready) return;
    const root = document.documentElement;
    let ownership = rootOwnershipRef.current;
    if (!ownership || ownership.root !== root) {
      if (ownership) restoreRootTheme(ownership);
      ownership = {
        root,
        theme: { previous: root.getAttribute("data-theme"), written: null },
        preference: { previous: root.getAttribute("data-theme-preference"), written: null },
        colorScheme: {
          previous: root.style.getPropertyValue("color-scheme"), written: null,
          previousPriority: root.style.getPropertyPriority("color-scheme"),
        },
      };
      rootOwnershipRef.current = ownership;
    }
    writeOwnedAttribute(root, "data-theme", ownership.theme, state.appearance.palette);
    writeOwnedAttribute(root, "data-theme-preference", ownership.preference, state.appearance.preference);
    const colorScheme = ownership.colorScheme;
    const current = root.style.getPropertyValue("color-scheme");
    const priority = root.style.getPropertyPriority("color-scheme");
    if (colorScheme.written !== null && (current !== colorScheme.written || priority !== "")) {
      colorScheme.previous = current;
      colorScheme.previousPriority = priority;
    }
    root.style.setProperty("color-scheme", state.appearance.nativeBrightness);
    colorScheme.written = state.appearance.nativeBrightness;
    // Cleanup belongs to the provider lifetime, not each palette update.
  }, [state.ready, state.appearance]);

  useEffect(() => {
    const brightness = state.appearance.nativeBrightness;
    if (!state.ready || !onThemeChange || notifiedBrightnessRef.current === brightness) return;
    notifiedBrightnessRef.current = brightness;
    try { onThemeChange(brightness); } catch { /* Native chrome cannot invalidate the UI preference. */ }
  }, [state.ready, state.appearance.nativeBrightness, onThemeChange]);

  const value = useMemo(() => ({ ...state, setPreference }), [state, setPreference]);
  return <ThemePreferencesContext.Provider value={value}>{children}</ThemePreferencesContext.Provider>;
}

export function WorkbenchThemeBoundary({ children, onThemeChange }: ThemeProviderProps) {
  const existing = useContext(ThemePreferencesContext);
  return existing ? <>{children}</> : <ThemeProvider onThemeChange={onThemeChange}>{children}</ThemeProvider>;
}

export function useThemePreferences(): ThemePreferences {
  const preferences = useContext(ThemePreferencesContext);
  if (!preferences) throw new Error("useThemePreferences must be used within a ThemeProvider.");
  return preferences;
}
