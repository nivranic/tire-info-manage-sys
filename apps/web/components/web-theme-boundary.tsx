"use client";

import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { ThemeProvider, useThemePreferences } from "./theme-preferences";
import type { ThemePalette } from "./theme-preference-values";

const THEME_COLORS: Record<ThemePalette, string> = {
  light: "#f6f5f1",
  dark: "#191d1c",
  "high-contrast": "#000000",
};

interface ThemeColorOwnership {
  node: HTMLMetaElement;
  previous: string | null;
  written: string;
}

function uniqueThemeColorMeta(): HTMLMetaElement | null {
  const nodes = document.head.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]');
  return nodes.length === 1 && !nodes[0].hasAttribute("media") ? nodes[0] : null;
}

function ThemeColorSync() {
  const { appearance, ready } = useThemePreferences();
  const ownershipRef = useRef<ThemeColorOwnership | null>(null);
  const relinquishedRef = useRef(false);

  useEffect(() => {
    relinquishedRef.current = false;
    return () => {
      const ownership = ownershipRef.current;
      ownershipRef.current = null;
      if (!ownership || uniqueThemeColorMeta() !== ownership.node
        || ownership.node.getAttribute("content") !== ownership.written) return;
      if (ownership.previous === null) ownership.node.removeAttribute("content");
      else ownership.node.setAttribute("content", ownership.previous);
    };
  }, []);

  useEffect(() => {
    if (!ready || relinquishedRef.current) return;
    const node = uniqueThemeColorMeta();
    let ownership = ownershipRef.current;
    if (ownership) {
      if (!node || node !== ownership.node || node.getAttribute("content") !== ownership.written) {
        // An external owner changed the target. Leave it alone until remount.
        ownershipRef.current = null;
        relinquishedRef.current = true;
        return;
      }
    } else {
      // Next owns creation of this tag; ambiguous or absent metadata is a no-op.
      if (!node) return;
      ownership = { node, previous: node.getAttribute("content"), written: THEME_COLORS[appearance.palette] };
      ownershipRef.current = ownership;
    }
    const color = THEME_COLORS[appearance.palette];
    ownership.node.setAttribute("content", color);
    ownership.written = color;
    // Restore only at the sync component's lifetime boundary, not each update.
  }, [ready, appearance.palette]);

  return null;
}

export default function WebThemeBoundary({ children }: { children: ReactNode }) {
  return <ThemeProvider><ThemeColorSync />{children}</ThemeProvider>;
}
