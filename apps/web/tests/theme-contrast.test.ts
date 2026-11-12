import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const themes = [...css.matchAll(/(?:^|\n)(:root[^{}]*)\{([^{}]+)\}/g)].map(([, selector, body]) => ({
  name: selector.includes('data-theme="high-contrast"') ? "high-contrast" : selector.includes('data-theme="dark"') ? "dark" : "light",
  colors: Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[a-f\d]{3,6})\s*;/gi)].map(([, name, value]) => [name, value])),
}));

function rgb(value: string): number[] {
  const hex = value.slice(1);
  const full = hex.length === 3 ? [...hex].map(char => char + char).join("") : hex;
  return [0, 2, 4].map(offset => parseInt(full.slice(offset, offset + 2), 16) / 255);
}

function luminance(channels: number[]): number {
  const linear = channels.map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}

function contrast(foreground: number[], background: number[]): number {
  const light = luminance(foreground);
  const dark = luminance(background);
  return (Math.max(light, dark) + 0.05) / (Math.min(light, dark) + 0.05);
}

test("the shared CSS defines each of the three explicit palettes", () => {
  assert.deepEqual(themes.map(theme => theme.name), ["light", "dark", "high-contrast"]);
});

const pairs = [
  ["muted", "paper"], ["muted", "surface"], ["muted", "sidebar"],
  ["accent", "paper"], ["accent", "sidebar"], ["accent", "accent-soft"],
  ["ink", "paper"], ["ink", "surface"], ["green", "green-soft"],
  ["warning", "paper"], ["warning", "surface"],
] as const;

for (const theme of themes) {
  test(`${theme.name} text and status colors meet normal-text contrast`, () => {
    for (const [foreground, background] of pairs) {
      const ratio = contrast(rgb(theme.colors[foreground]), rgb(theme.colors[background]));
      assert.ok(ratio >= 4.5, `${foreground} on ${background} has contrast ${ratio.toFixed(2)}`);
    }
  });
}

test("navigation hints retain normal-text contrast after opacity blending", () => {
  const body = css.match(/\.nav-item small\s*\{([^}]+)\}/)?.[1];
  assert.ok(body);
  const opacity = Number(body.match(/opacity:\s*([\d.]+)/)?.[1] ?? 1);
  for (const theme of themes) {
    const foreground = rgb(theme.colors.muted);
    const background = rgb(theme.colors.sidebar);
    const blended = foreground.map((value, index) => value * opacity + background[index] * (1 - opacity));
    const ratio = contrast(blended, background);
    assert.ok(ratio >= 4.5, `${theme.name} navigation hint has contrast ${ratio.toFixed(2)}`);
  }
});
