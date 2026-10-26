import assert from "node:assert/strict";
import { test } from "node:test";
import { parseThemePreference, resolveThemeAppearance, THEME_STORAGE_KEY } from "../components/theme-preference-values.ts";
import type { NativeBrightness, ThemeAppearance, ThemeChangeHandler, ThemePreference } from "../components/theme-preference-values.ts";

test("the existing storage key and exact light/dark values remain compatible", () => {
  assert.equal(THEME_STORAGE_KEY, "tire-theme-v1");
  for (const preference of ["light", "dark"] as const) {
    assert.equal(parseThemePreference(preference), preference);
    assert.equal(resolveThemeAppearance(parseThemePreference(preference), preference !== "dark").preference, preference);
  }
});

test("all four canonical stored preferences are accepted without normalization", () => {
  const preferences: readonly ThemePreference[] = ["system", "light", "dark", "high-contrast"];
  for (const preference of preferences) assert.equal(parseThemePreference(preference), preference);
});

test("missing, malformed and non-string storage values fall back to system", () => {
  const invalid: readonly unknown[] = [
    null, undefined, "", "LIGHT", "Dark", "SYSTEM", "High-Contrast", " light ", "contrast", '"dark"',
    0, 1, true, false, [], ["dark"], Object.freeze({ preference: "dark" }),
    Object.freeze({ toString() { throw new Error("must not coerce stored values"); } }),
  ];
  for (const raw of invalid) assert.equal(parseThemePreference(raw), "system");
});

test("system keeps its preference while resolving each environment and native brightness", () => {
  const cases: readonly [boolean, ThemeAppearance][] = [
    [false, { preference: "system", palette: "light", nativeBrightness: "light" }],
    [true, { preference: "system", palette: "dark", nativeBrightness: "dark" }],
  ];
  for (const [systemDark, expected] of cases) {
    assert.deepEqual(resolveThemeAppearance("system", systemDark), expected);
  }
});

test("explicit palettes ignore system changes and high contrast uses dark native chrome", () => {
  const cases: readonly ThemeAppearance[] = [
    { preference: "light", palette: "light", nativeBrightness: "light" },
    { preference: "dark", palette: "dark", nativeBrightness: "dark" },
    { preference: "high-contrast", palette: "high-contrast", nativeBrightness: "dark" },
  ];
  for (const expected of cases) {
    for (const systemDark of [false, true]) {
      assert.deepEqual(resolveThemeAppearance(expected.preference, systemDark), expected);
    }
  }
});

test("appearance fits the existing single-argument light/dark callback contract", () => {
  const observed: NativeBrightness[] = [];
  const legacyConsumer = (theme: "light" | "dark") => { observed.push(theme); };
  const onThemeChange: ThemeChangeHandler = legacyConsumer;
  const cases: readonly [ThemePreference, boolean, NativeBrightness][] = [
    ["system", false, "light"], ["system", true, "dark"], ["light", true, "light"],
    ["dark", false, "dark"], ["high-contrast", false, "dark"],
  ];
  for (const [preference, systemDark] of cases) {
    const appearance = resolveThemeAppearance(preference, systemDark);
    assert.deepEqual(Object.keys(appearance).sort(), ["nativeBrightness", "palette", "preference"]);
    onThemeChange(appearance.nativeBrightness);
  }
  assert.deepEqual(observed, cases.map(([, , expected]) => expected));
});

test("resolving preferences leaves frozen inputs and earlier results unchanged", () => {
  const input = Object.freeze({ preference: "system" as const, systemDark: false });
  const initial = resolveThemeAppearance(input.preference, input.systemDark);
  Object.freeze(initial);
  const later = resolveThemeAppearance(input.preference, true);
  assert.deepEqual(input, { preference: "system", systemDark: false });
  assert.deepEqual(initial, { preference: "system", palette: "light", nativeBrightness: "light" });
  assert.deepEqual(later, { preference: "system", palette: "dark", nativeBrightness: "dark" });
  assert.notEqual(initial, later);
});
