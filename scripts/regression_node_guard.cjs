/* Reviewed Node wire children only. JS API fence, not an OS sandbox. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL, fileURLToPath } = require('node:url');
const { registerHooks, syncBuiltinESMExports } = require('node:module');
const privateRoot = fs.realpathSync(process.env.R82_PRIVATE_ROOT);
const repoRoot = fs.realpathSync(process.env.R82_REPO_ROOT);
function deny(category) { throw new Error(`r82_node_boundary:${category}`); }
function inside(value, root) {
  const relative = path.relative(root, path.resolve(value));
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}
if (!inside(fs.realpathSync(process.cwd()), privateRoot)) deny('cwd_outside');
for (const key of ['TEMP', 'TMP', 'TMPDIR', 'TI_OBJECT_STORE_ROOT', 'TI_PARSER_BUNDLE_ROOT']) {
  if (!inside(process.env[key], privateRoot)) deny('environment_path');
}
const block = (object, names, category) => {
  for (const name of names) if (name in object) object[name] = () => deny(category);
};
const net = require('node:net');
block(net, ['connect', 'createConnection', 'createServer'], 'network');
block(net.Socket.prototype, ['connect'], 'network');
block(net.Server.prototype, ['listen'], 'network');
block(require('node:tls'), ['connect', 'createServer'], 'network');
for (const module of ['node:http', 'node:https']) {
  block(require(module), ['request', 'get', 'createServer'], 'network');
}
block(require('node:http2'), ['connect', 'createServer', 'createSecureServer'], 'network');
block(require('node:dgram'), ['createSocket'], 'network');
for (const target of [require('node:dns'), require('node:dns').promises]) {
  block(target, ['lookup', 'lookupService', 'resolve', 'resolve4', 'resolve6', 'resolveAny',
    'resolveCaa', 'resolveCname', 'resolveMx', 'resolveNaptr', 'resolveNs', 'resolvePtr',
    'resolveSoa', 'resolveSrv', 'resolveTxt', 'reverse'], 'network_dns');
  if (target.Resolver) block(target.Resolver.prototype, Object.getOwnPropertyNames(target.Resolver.prototype)
    .filter(name => name.startsWith('resolve') || name === 'reverse'), 'network_dns');
}
globalThis.fetch = () => deny('network_fetch');
globalThis.WebSocket = class { constructor() { deny('network_websocket'); } };
block(require('node:child_process'), ['exec', 'execSync', 'execFile', 'execFileSync', 'spawn', 'spawnSync', 'fork'], 'descendant_process');
block(require('node:cluster'), ['fork', 'setupPrimary', 'setupMaster'], 'descendant_process');
require('node:worker_threads').Worker = class { constructor() { deny('worker'); } };
process.dlopen = () => deny('native_addon');
if (process.getBuiltinModule) {
  const getBuiltinModule = process.getBuiltinModule;
  process.getBuiltinModule = function (specifier) {
    if (specifier === 'sqlite' || specifier === 'node:sqlite') deny('database_module');
    return getBuiltinModule.call(this, specifier);
  };
}
// These fixed wire cases are read-only. Denying every FS mutation also keeps
// native SQLite objects from being created via ordinary fs APIs.
const mutations = ['writeFile', 'appendFile', 'write', 'writev', 'mkdir', 'mkdtemp', 'rm',
  'rmdir', 'unlink', 'rename', 'copyFile', 'cp', 'link', 'symlink', 'truncate', 'ftruncate',
  'chmod', 'fchmod', 'lchmod', 'chown', 'fchown', 'lchown', 'utimes', 'futimes', 'lutimes'];
block(fs, mutations.flatMap(name => [name, `${name}Sync`]), 'filesystem_write');
block(fs.promises, mutations, 'filesystem_write');
block(fs, ['createWriteStream'], 'filesystem_write');
function readFlags(flags) { return flags === undefined || flags === 'r' || flags === 'rs' || flags === fs.constants.O_RDONLY; }
for (const name of ['open', 'openSync']) {
  const original = fs[name];
  fs[name] = function (filename, flags, ...rest) {
    if (!readFlags(flags)) deny('filesystem_write');
    return original.call(this, filename, flags, ...rest);
  };
}
const originalOpen = fs.promises.open;
fs.promises.open = function (filename, flags, ...rest) {
  if (!readFlags(flags)) deny('filesystem_write');
  return originalOpen.call(this, filename, flags, ...rest);
};
// Only this fixed, non-symlink entry may resolve as an .mts module.
const rawEvidenceSdkPath = path.join(repoRoot, 'packages/api-client/tests/raw-evidence-v2.mts');
const rawEvidenceSdkRealPath = fs.realpathSync(rawEvidenceSdkPath);
if (rawEvidenceSdkRealPath !== rawEvidenceSdkPath) deny('mts_entry_realpath');
const rawEvidenceSdkUrl = pathToFileURL(rawEvidenceSdkRealPath).href;
// No SQLite module (including read-only normal databases) is needed by a DTO
// wire replay. Fixed package imports resolve as if eval was at the repo root.
registerHooks({ resolve(specifier, context, nextResolve) {
  if (specifier === 'node:sqlite' || /^(better-sqlite3|sqlite3|pg|mysql2?)(\/|$)/.test(specifier)) deny('database_module');
  let target = specifier;
  if (specifier === '@tire/api-client') {
    target = pathToFileURL(path.join(repoRoot, 'packages/api-client/src/index.ts')).href;
  } else if (specifier === 'regression:raw-evidence-v2-sdk') {
    target = rawEvidenceSdkUrl;
  }
  const resolved = nextResolve(target, context);
  let url;
  try { url = new URL(resolved.url); } catch { deny('module_url'); }
  if (url.protocol === 'file:') {
    let filename;
    try { filename = fileURLToPath(url); } catch { deny('module_url'); }
    if (path.extname(filename).toLowerCase() === '.mts') {
      if (url.search || url.hash || url.href !== rawEvidenceSdkUrl) deny('unreviewed_mts');
      let realUrl;
      try { realUrl = pathToFileURL(fs.realpathSync(filename)).href; } catch { deny('unreviewed_mts'); }
      if (realUrl !== rawEvidenceSdkUrl) deny('unreviewed_mts');
    }
  }
  return resolved;
} });
syncBuiltinESMExports();
