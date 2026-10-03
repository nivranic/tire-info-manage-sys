import { createHash } from "node:crypto";
import { readFile, writeFile, mkdir, readdir } from "node:fs/promises";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "apps", "web");
const distDir = process.env.TI_NEXT_DIST_DIR || ".next";
if (!/^[.a-zA-Z0-9_-]+$/.test(distDir) || distDir === "." || distDir === "..") {
  throw new Error("TI_NEXT_DIST_DIR must name a build directory inside apps/web.");
}
const icons = [192, 512, 180];
if (process.argv.includes("--icons")) {
  const { default: sharp } = await import("sharp");
  await mkdir(join(root, "public", "icons"), { recursive: true });
  for (const size of icons) {
    await sharp(join(root, "app", "icon.svg"), { density: 600 }).resize(size, size).png().toFile(join(root, "public", "icons", `icon-${size}.png`));
  }
  const png = await sharp(join(root, "app", "icon.svg"), { density: 200 }).resize(32, 32).png().toBuffer();
  const header = Buffer.alloc(22);
  header.writeUInt16LE(1, 2); header.writeUInt16LE(1, 4);
  header[6] = 32; header[7] = 32; header.writeUInt16LE(1, 10); header.writeUInt16LE(32, 12);
  header.writeUInt32LE(png.length, 14); header.writeUInt32LE(22, 18);
  await writeFile(join(root, "public", "favicon.ico"), Buffer.concat([header, png]));
} else {
  const prerender = JSON.parse(await readFile(join(root, distDir, "prerender-manifest.json"), "utf8"));
  if (!prerender.routes["/"] || prerender.routes["/"].initialRevalidateSeconds !== false) {
    throw new Error("PWA shell must be fully prerendered, without user-specific server data.");
  }
  const buildId = (await readFile(join(root, distDir, "BUILD_ID"), "utf8")).trim();
  const staticRoot = join(root, distDir, "static");
  async function walk(path) {
    const results = [];
    for (const entry of await readdir(path, { withFileTypes: true })) {
      const full = join(path, entry.name);
      if (entry.isDirectory()) results.push(...await walk(full));
      else if (/\.(?:js|css|woff2?)$/.test(entry.name)) results.push("/_next/static/" + relative(staticRoot, full).split(sep).join("/"));
    }
    return results;
  }
  const assets = ["/", "/manifest.webmanifest", "/favicon.ico", ...icons.map(size => `/icons/icon-${size}.png`), ...await walk(staticRoot)].sort();
  const template = await readFile(join(root, "pwa", "worker.js"), "utf8");
  const version = createHash("sha256").update(JSON.stringify({ buildId, assets, template })).digest("hex").slice(0, 24);
  await writeFile(join(root, "public", "sw.js"), template.replace("__TIRE_PWA_CONFIG__", JSON.stringify({ version, assets })), "utf8");
  console.log(`PWA shell: ${assets.length} allowlisted assets, version ${version}; API and evidence are never cached.`);
}
