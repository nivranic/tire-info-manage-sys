/** Test-only, byte-bound access to the portable synthetic contract corpus. */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const CORPUS_URL = new URL("../../../domain-types/fixtures/device-ai-v1/", import.meta.url);
const PROVENANCE_SHA256 = "278e8cacad9a8537264781e49ce381111e6ed50b17a224aa32ccdf066012172d";
/** @typedef {{path: string, source_path: string, sha256: string, byte_count: number}} Entry */
const digest = raw => createHash("sha256").update(raw).digest("hex");

function assertRelativePath(path) {
  if (!path || path.includes("\\") || path.includes(":")
    || path.split("/").some(part => !part || part === "." || part === "..")) {
    throw new Error(`invalid contract corpus path: ${path}`);
  }
}

const provenanceBytes = readFileSync(new URL("provenance.json", CORPUS_URL));
if (digest(provenanceBytes) !== PROVENANCE_SHA256) throw new Error("contract corpus provenance SHA drift");
const provenance = JSON.parse(provenanceBytes.toString("utf8"));
if (provenance.schema !== "device-ai-test-corpus-provenance@1"
  || provenance.source_root !== ".artifacts/device-ai50" || provenance.synthetic_only !== true
  || provenance.file_count !== 127 || provenance.files.length !== provenance.file_count) {
  throw new Error("contract corpus provenance contract drift");
}
/** @type {Map<string, Entry>} */
const entries = new Map();
for (const entry of provenance.files) {
  assertRelativePath(entry.path);
  if (entries.has(entry.path) || entry.source_path !== `${provenance.source_root}/${entry.path}`
    || !/^[0-9a-f]{64}$/.test(entry.sha256) || !Number.isSafeInteger(entry.byte_count) || entry.byte_count < 0) {
    throw new Error(`invalid contract corpus binding: ${entry.path}`);
  }
  entries.set(entry.path, entry);
}

/** @param {string} path @returns {Uint8Array} */
export function readCorpusBytes(path) {
  assertRelativePath(path);
  const entry = entries.get(path);
  if (!entry) throw new Error(`unbound contract corpus file: ${path}`);
  const raw = readFileSync(new URL(path, CORPUS_URL));
  if (raw.byteLength !== entry.byte_count || digest(raw) !== entry.sha256) {
    throw new Error(`contract corpus bytes drift: ${path}`);
  }
  return raw;
}

/** @template T @param {string} path @returns {T} */
export function readCorpusJson(path) {
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(readCorpusBytes(path)));
}

// The suite fails before replay if any part of the reference closure is absent
// or changed. Actual consumer reads are checked again over their returned bytes.
for (const path of entries.keys()) readCorpusBytes(path);
