/** Independent manifest-pinned corpus; no ignored artifact is a runtime input. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const MANIFEST_SHA256 = "c1d454ce4875a9d9c6e77fc8dd9f59ae4ae147ca0ca030af553e83bae14525d1";
export const DEFAULT_ROOT = fileURLToPath(new URL("../../../domain-types/fixtures/device-ai-capacity-v1/", import.meta.url));
export const sha256 = raw => createHash("sha256").update(raw).digest("hex");
export function checkBytes(raw, size, digest) {
  assert(Number.isSafeInteger(size) && raw.byteLength === size, "capacity corpus byte count drift");
  assert.equal(sha256(raw), digest, "capacity corpus SHA drift");
}
function relativePath(value) {
  assert(typeof value === "string" && value.length > 0 && !/[\\:]/.test(value)
    && !path.posix.isAbsolute(value) && value.split("/").every(part => part && part !== "." && part !== ".."), "invalid capacity corpus path");
}
export class CapacityCorpus {
  constructor(root = DEFAULT_ROOT) {
    this.root = realpathSync(root);
    const raw = readFileSync(path.join(this.root, "manifest.json"));
    assert.equal(sha256(raw), MANIFEST_SHA256, "capacity manifest SHA drift");
    const manifest = JSON.parse(raw.toString("utf8"));
    assert.equal(manifest.schema, "device-ai-capacity-corpus@1");
    assert.equal(manifest.synthetic_only, true);
    assert.equal(manifest.max_package_bytes, 8_388_608);
    this.entries = new Map();
    for (const entry of manifest.files) {
      relativePath(entry.path);
      assert(!this.entries.has(entry.path), "duplicate capacity corpus path");
      this.entries.set(entry.path, entry);
    }
    for (const relative of this.entries.keys()) this.readBytes(relative);
  }
  readBytes(relative) {
    relativePath(relative);
    const entry = this.entries.get(relative);
    assert(entry, "unbound capacity corpus file");
    const target = realpathSync(path.join(this.root, relative));
    const resolvedRelative = path.relative(this.root, target);
    assert(resolvedRelative && !path.isAbsolute(resolvedRelative)
      && resolvedRelative.split(path.sep)[0] !== "..", "capacity corpus escaped root");
    const raw = readFileSync(target);
    checkBytes(raw, entry.byte_count, entry.sha256);
    return raw;
  }
  readJson(relative) { return JSON.parse(this.readBytes(relative).toString("utf8")); }
  expand(item) {
    const recipe = item.input;
    assert.equal(recipe.form, "repeat_hex");
    assert(Number.isSafeInteger(recipe.repeat_count) && recipe.repeat_count >= 0 && recipe.repeat_count <= 8_388_609);
    const decode = key => {
      assert(typeof recipe[key] === "string" && /^(?:[0-9a-f]{2})*$/.test(recipe[key]));
      return Buffer.from(recipe[key], "hex");
    };
    const prefix = decode("prefix_hex"), repeat = decode("repeat_hex"), suffix = decode("suffix_hex");
    assert.equal(prefix.length + repeat.length * recipe.repeat_count + suffix.length, item.input_byte_count);
    const raw = Buffer.alloc(item.input_byte_count);
    prefix.copy(raw);
    if (recipe.repeat_count) raw.fill(repeat, prefix.length, raw.length - suffix.length);
    suffix.copy(raw, raw.length - suffix.length);
    checkBytes(raw, item.input_byte_count, item.input_sha256);
    return raw;
  }
  formalBytes(spec, item) {
    assert(Number.isSafeInteger(item.padding_spaces) && item.padding_spaces >= 0 && item.padding_spaces <= 8_388_609);
    const raw = Buffer.concat([this.readBytes(spec.base_pack), Buffer.alloc(item.padding_spaces, 0x20)]);
    checkBytes(raw, item.input_byte_count, item.input_sha256);
    return raw;
  }
}
export const CORPUS = new CapacityCorpus();
