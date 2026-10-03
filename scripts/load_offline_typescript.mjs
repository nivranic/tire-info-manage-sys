import { readFile } from "node:fs/promises";
import ts from "typescript";
const modules = new Map();
export async function offlineModuleUrl(url) {
  if (modules.has(url.href)) return modules.get(url.href);
  const pending = (async () => {
    if (url.pathname.endsWith(".json")) return `data:text/javascript;base64,${Buffer.from("export default " + await readFile(url, "utf8")).toString("base64")}`;
    let output = ts.transpileModule(await readFile(url, "utf8"), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
    const imports = [...output.matchAll(/(?:from\s+|import\s*)["'](\.[^"']+|@tire\/api-client|@tire\/native-client)["']/g)];
    for (const match of imports) {
      const specifier = match[1], target = specifier === "@tire/api-client" || specifier === "@tire/native-client" ? new URL("../packages/" + specifier.slice(6) + "/src/index.ts", import.meta.url) : new URL(/\.(ts|json)$/.test(specifier) ? specifier : specifier + ".ts", url);
      output = output.replaceAll(JSON.stringify(specifier), JSON.stringify(await offlineModuleUrl(target)));
    }
    output += `\n//# sourceURL=${url.href}\n`;
    return `data:text/javascript;base64,${Buffer.from(output).toString("base64")}`;
  })();
  modules.set(url.href, pending); return pending;
}
export async function loadOfflineTypeScript(relative, from) { return import(await offlineModuleUrl(new URL(relative, from))); }
