// Selftest-only Node module hooks so the api-client package sources (written
// for the bundler resolver: extensionless relative imports and a bare .json
// import) run under `node --experimental-transform-types` without touching
// product sources or the root tsconfig:
//   resolve — retries a relative extensionless specifier with ".ts" appended;
//   load    — serves .json modules as an ESM default export (import attributes
//             are mandatory for JSON in strict Node ESM otherwise).
// Node >= 22.15 registerHooks (synchronous customization hooks).
import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

registerHooks({
  resolve(specifier, context, nextResolve) {
    try {
      return nextResolve(specifier, context);
    } catch (error) {
      const relative = specifier.startsWith("./") || specifier.startsWith("../");
      if (relative && !/\.[cm]?[jt]sx?$/i.test(specifier)) {
        return nextResolve(`${specifier}.ts`, context);
      }
      throw error;
    }
  },
  load(url, context, nextLoad) {
    if (url.startsWith("file:") && url.endsWith(".json")) {
      const parsed = JSON.parse(readFileSync(fileURLToPath(url), "utf8"));
      return { format: "module", shortCircuit: true, source: `export default ${JSON.stringify(parsed)};` };
    }
    return nextLoad(url, context);
  },
});
