// Test-only portability fence: npm test must work without ignored evidence.
// Installed before the JSON/TS hook; no product transport or source is patched.
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { fileURLToPath } from "node:url";

const readFileSync = fs.readFileSync;
fs.readFileSync = function (path, ...options) {
  const filename = path instanceof URL ? fileURLToPath(path) : String(path);
  if (/(^|[\\/])\.artifacts([\\/]|$)/i.test(filename)) {
    throw new Error("Device AI contract tests must read tracked fixtures only; ignored .artifacts reads are forbidden.");
  }
  return readFileSync.call(this, path, ...options);
};
syncBuiltinESMExports();
