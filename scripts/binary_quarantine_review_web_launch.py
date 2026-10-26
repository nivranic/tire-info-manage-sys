"""R98 fixed private API/Next service candidate. Review before freeze, then review freeze before run.

Only this invocation's suspended Popen trees join two new Windows Jobs. No old
wrapper authorization is inherited. JS/Python guards are not an OS sandbox.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import http.client as http_client
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
PYTHON = ROOT / 'apps/api/.venv/Scripts/python.exe'
VENV = ROOT / 'apps/api/.venv'
BASE_PYTHON = Path('D:/.PYENV/pyenv-win/versions/3.12.10')
API_PYTHON = BASE_PYTHON / 'python.exe'
API_PYTHON_PIN = {'bytes': 104952, 'sha256': '4d6f5f81a4bca11191c4c7c6b43632694d0a4ce74e068619d8fdc161d469859a'}
NODE = Path('E:/DevTools/nvm/v22.22.1/node.exe')
NODE_PIN = {'bytes': 87059456, 'sha256': '923a41f268ab49ede2e3363fbdd9e790609e385c6f3ca880b4ee9a56a8133e5a'}
NEXT = ROOT / 'node_modules/next/dist/bin/next'
SUPERVISOR = ROOT / 'scripts/binary_quarantine_review_native_verify.py'
FIXTURE = ROOT / 'scripts/binary_quarantine_review_web_fixture.py'
QA = ROOT / 'scripts/binary_quarantine_review_web_ui_qa.mjs'
S2 = ROOT / '.artifacts/r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f/xiaomi-first-generation-2.pdf'
S2_PIN = {'bytes': 3240150, 'sha256': '0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f'}
CONSOLE = Path('C:/Windows/System32/conhost.exe')
CONSOLE_PIN = {'bytes': 1003520, 'sha256': 'c86146188b78e484f32cc29e2331689659943b47689a85570342044f499938ac'}
CONSOLE_ARGV = r'\??\C:\WINDOWS\system32\conhost.exe 0xffffffff -ForceV1'
CONSOLE_ARGVS = (CONSOLE_ARGV, r'\??\C:\WINDOWS\system32\conhost.exe 0x4')
API_PORT, WEB_PORT = 18986, 18987

# Generated only into a future fresh private output; no Node is run by freeze.
PRELOAD = r'''"use strict";
const fs = require('node:fs'), path = require('node:path'), net = require('node:net');
const { syncBuiltinESMExports, registerHooks } = require('node:module');
const out = process.env.R98_LAUNCH_OUTPUT;
if (!out || !/^r98wl-[a-f0-9]{16}$/.test(path.basename(out))) throw Error('r98_service_guard_config');
const append = fs.appendFileSync.bind(fs), log = path.join(out, 'node-guard.jsonl');
const lstat = fs.lstatSync.bind(fs), realpath = fs.realpathSync.native.bind(fs.realpathSync);
let auditing = false;
function audit(value) {
  if (auditing) throw Error('r98_audit_path_invalid');
  auditing = true;
  try { writeAllowed(log); append(log, JSON.stringify({at:new Date().toISOString(), pid:process.pid, ...value})+'\n'); }
  finally { auditing = false; }
}
function deny(category) { if (!auditing) audit({event:'denied', category}); throw Error('r98_service_boundary:'+category); }
const block = (obj, names, category) => { for (const name of names) if (name in obj) obj[name] = () => deny(category); };
const inside = p => { const rel = path.relative(out, path.resolve(p)); return rel === '' || (!rel.startsWith('..'+path.sep) && rel !== '..' && !path.isAbsolute(rel)); };
function writeAllowed(p) {
  if (typeof p !== 'string' && !(p instanceof URL) && !Buffer.isBuffer(p)) return deny('fd_mutation');
  p = p instanceof URL ? require('node:url').fileURLToPath(p) : p.toString();
  const windows = p.replaceAll('/', '\\');
  if (/^\\\\[?.]\\/.test(windows) || windows.slice(2).includes(':') || /^[A-Za-z]:[^\\]/.test(windows)) return deny('write_device_ads_or_drive_relative');
  const target = path.resolve(p);
  if (!inside(target)) return deny('write_outside_private_output');
  const same = (a,b) => path.toNamespacedPath(path.resolve(a)).toLowerCase() === path.toNamespacedPath(path.resolve(b)).toLowerCase();
  for (let parent=target;;parent=path.dirname(parent)) {
    let metadata;
    try { metadata=lstat(parent); }
    catch(error) { if(error.code!=='ENOENT')return deny('write_ancestor_unreadable'); }
    if(metadata) {
      if(metadata.isSymbolicLink())return deny('write_reparse');
      let actual;
      try { actual=realpath(parent); } catch { return deny('write_realpath_unavailable'); }
      if(!same(actual,parent))return deny('write_redirected_ancestor');
      if(parent===target&&metadata.isFile()&&metadata.nlink>1)return deny('write_hardlink');
    }
    if(path.dirname(parent)===parent)break;
  }
}
const readBits = ['O_SYNC','O_DSYNC','O_NOFOLLOW','O_NOATIME','O_DIRECT','O_NONBLOCK','O_CLOEXEC','O_DIRECTORY'].reduce((bits,name)=>bits|(fs.constants[name]||0),0);
const writeBits = ['O_WRONLY','O_RDWR','O_APPEND','O_CREAT','O_TRUNC','O_EXCL','O_TMPFILE'].reduce((bits,name)=>bits|(fs.constants[name]||0),0);
function readOnlyFlag(flag) {
  if(flag===undefined||flag==='r'||flag==='rs'||flag==='sr')return true;
  return typeof flag==='number'&&Number.isSafeInteger(flag)&&flag>=0&&flag<=0x7fffffff
    &&(flag&writeBits)===0&&(flag&~readBits)===0;
}
function readOptions(options) {
  if(options&&typeof options==='object'&&(!readOnlyFlag(options.flag)||!readOnlyFlag(options.flags)))deny('read_api_write_flags');
}
function endpoint(args) {
  if (args[0] && typeof args[0] === 'object') return {host:args[0].host || args[0].hostname, port:Number(args[0].port), path:args[0].path};
  return {port:Number(args[0]), host:typeof args[1] === 'string' ? args[1] : undefined};
}
let listenerCount = 0;
const listen = net.Server.prototype.listen;
net.Server.prototype.listen = function(...args) {
  const e = endpoint(args);
  if (listenerCount || e.path || e.host !== '127.0.0.1' || e.port !== 18987) return deny('listener');
  listenerCount++; audit({event:'listener_requested', ...e});
  this.once('close', () => audit({event:'listener_closed'}));
  return listen.apply(this,args);
};
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function(...args) {
  // Node's internal normalizeArgs returns [options, callback] with a private
  // symbol. Inspect its options without changing the original call arguments.
  const normalized = Array.isArray(args[0]) ? args[0] : args;
  const e = endpoint(normalized);
  if (e.path || e.host !== '127.0.0.1' || e.port !== 18986) return deny('outbound_socket');
  audit({event:'api_connect', ...e}); return connect.apply(this,args);
};
for (const name of ['node:tls','node:https','node:http2']) block(require(name), ['connect','createConnection','request','get','createServer','createSecureServer'], 'tls_or_http2');
block(require('node:dgram'), ['createSocket'], 'datagram');
for (const target of [require('node:dns'), require('node:dns').promises]) {
  block(target, Object.keys(target).filter(n => n === 'lookupService' || n === 'reverse' || n.startsWith('resolve')), 'dns');
  if (target.Resolver) block(target.Resolver.prototype, Object.getOwnPropertyNames(target.Resolver.prototype).filter(n => n.startsWith('resolve') || n === 'reverse'), 'dns');
}
require('node:dns').lookup = function(host, options, callback) {
  if (host !== '127.0.0.1') return deny('dns_lookup');
  if (typeof options === 'function') { callback=options; options={}; }
  process.nextTick(() => options?.all ? callback(null,[{address:host,family:4}]) : callback(null,host,4));
};
require('node:dns').promises.lookup = async function(host, options) {
  if (host !== '127.0.0.1') return deny('dns_lookup');
  return options?.all ? [{address:host,family:4}] : {address:host,family:4};
};
globalThis.fetch = () => deny('fetch'); globalThis.WebSocket = class { constructor(){deny('websocket');} };
block(require('node:child_process'), ['exec','execSync','execFile','execFileSync','spawn','spawnSync','fork'], 'child');
block(require('node:cluster'), ['fork','setupPrimary','setupMaster'], 'cluster');
require('node:worker_threads').Worker = class { constructor(){deny('worker');} };
registerHooks({resolve(specifier,context,nextResolve){ if (/^(?:node:sqlite|better-sqlite3|sqlite3|pg|mysql2?)(?:\/|$)/.test(specifier)) deny('database_module'); return nextResolve(specifier,context); }});
if (process.getBuiltinModule) { const original=process.getBuiltinModule; process.getBuiltinModule=name => /^(?:node:)?sqlite$/.test(name) ? deny('database_module') : original(name); }
for (const name of ['writeFile','appendFile','mkdir','mkdtemp','rm','rmdir','unlink','truncate','chmod','chown','utimes']) {
  for (const target of [fs,fs.promises]) for (const key of target===fs ? [name,name+'Sync'] : [name]) if (target[key]) {
    const original=target[key]; target[key]=function(p,...rest){writeAllowed(p);return original.call(this,p,...rest);};
  }
}
for(const target of [fs,fs.promises])block(target,['cp','cpSync','link','linkSync','symlink','symlinkSync'],'link_or_recursive_copy');
for (const name of ['rename','copyFile']) for (const target of [fs,fs.promises]) for (const key of target===fs ? [name,name+'Sync'] : [name]) if (target[key]) {
  const original=target[key]; target[key]=function(a,b,...rest){if(name==='rename')writeAllowed(a);writeAllowed(b);return original.call(this,a,b,...rest);};
}
for (const target of [fs,fs.promises]) for (const key of target===fs ? ['open','openSync'] : ['open']) {
  const original=target[key]; target[key]=function(p,flags,...rest){if(!readOnlyFlag(flags))writeAllowed(p);return original.call(this,p,flags,...rest);};
}
const stream=fs.createWriteStream;fs.createWriteStream=function(p,...rest){
  if(rest[0]&&typeof rest[0]==='object'&&rest[0].fd!==undefined&&rest[0].fd!==null)deny('write_stream_fd');
  writeAllowed(p);return stream.call(this,p,...rest);
};
for (const target of [fs,fs.promises]) for (const key of target===fs ? ['readFile','readFileSync'] : ['readFile']) {
  const original=target[key]; target[key]=function(p,...rest){readOptions(rest[0]);if(typeof p!=='number'&&/^\.env(?:\.|$)/i.test(path.basename(p instanceof URL?require('node:url').fileURLToPath(p):p.toString()))&&fs.existsSync(p))deny('environment_file');return original.call(this,p,...rest);};
}
const readStream=fs.createReadStream;fs.createReadStream=function(p,options){readOptions(options);return readStream.call(this,p,options);};
let line='';process.stdin.setEncoding('utf8');process.stdin.on('data',data=>{
  line+=data;if(line.length>32)deny('stdin_command');
  if(line.includes('\n')){if(line.trim()!=='stop'||!process.listenerCount('SIGTERM'))return deny('graceful_stop_not_ready');
    audit({event:'graceful_stop_requested'});process.emit('SIGTERM','SIGTERM');line='';}
});
audit({event:'started',argv:process.argv,execArgv:process.execArgv});
process.on('exit',code=>audit({event:'exit',code,active_resource_types:process.getActiveResourcesInfo()}));
syncBuiltinESMExports();
'''


def utc():
    return datetime.now(timezone.utc).isoformat()


def regular(path):
    path = Path(path)
    # Reject junctions as well as symlinks, including every existing ancestor.
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or bool(getattr(part.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400)):
            raise RuntimeError('reparse input/output forbidden: ' + str(part))
    return path


def digest(path):
    path = regular(path)
    if not path.is_file():
        raise RuntimeError('regular file required: ' + str(path))
    value = path.read_bytes()
    return {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}


def files(path, excluded=()):
    path = regular(path)
    if not path.is_dir():
        raise RuntimeError('regular directory required: ' + str(path))
    result = []
    for item in sorted(path.iterdir()):
        if item in excluded:
            continue
        regular(item)
        result.extend(files(item, excluded) if item.is_dir() else [item])
    return result


def manifest(paths):
    return {str(p): digest(p) for p in sorted(set(paths))}


def project_python_inputs():
    """Bind readable project bytecode too: -B disables writes, not cache reads."""
    tree_roots = (ROOT / 'apps/api/tire_api',)
    modules = (ROOT / 'apps/api/tests/test_vehicle_raw.py',
               ROOT / 'apps/api/tests/admin_support.py', SUPERVISOR)
    suffixes = ('.py', '.pyc', '.pyd')
    paths = {p for folder in tree_roots for p in files(folder) if p.suffix.lower() in suffixes}
    cache_scopes = []
    for source in modules:
        paths.add(source)
        module_stem = source.stem.casefold()
        # Include legacy sibling caches, extension alternatives and every
        # tagged/optimized cache variant for these exact imported modules.
        for folder in (source.parent, source.parent / '__pycache__'):
            regular(folder)
            cache_scopes.append({'directory': str(folder), 'module_stem': source.stem})
            if not folder.exists():
                continue
            if not folder.is_dir():
                raise RuntimeError('project Python module/cache directory required: ' + str(folder))
            for item in sorted(folder.iterdir()):
                name = item.name.casefold()  # The reviewed host uses Windows path matching.
                if name == module_stem or name.startswith(module_stem + '.'):
                    regular(item)
                    if not item.is_file():
                        raise RuntimeError('unreviewed project Python module shape: ' + str(item))
                    if item.suffix.lower() in suffixes:
                        paths.add(item)
    return {'tree_roots': [str(p) for p in tree_roots], 'module_sources': [str(p) for p in modules],
            'suffixes': list(suffixes), 'module_cache_scopes': cache_scopes, 'files': manifest(paths),
            'scope': 'Exact API Python tree plus three named helper/supervisor modules and all sibling/__pycache__ variants; unrelated test/script modules and other project/OS roots excluded.'}


def python_installation():
    """Read installed bytes/config only, never import a package or probe Python.

    The exact runtime roots are bounded to this base install and this venv.
    Shared Windows DLLs, registry/loader state and native side effects are not
    part of this snapshot or an OS isolation claim.
    """
    cfg = {}
    for line in (VENV / 'pyvenv.cfg').read_text(encoding='utf-8').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            cfg[key.strip().lower()] = value.strip()
    if (regular(Path(cfg.get('home', ''))).resolve() != BASE_PYTHON
            or cfg.get('implementation') != 'CPython' or cfg.get('version_info') != '3.12.10'
            or cfg.get('include-system-site-packages', '').lower() != 'false'):
        raise RuntimeError('reviewed exact base CPython and no global site-packages configuration required')
    # These path-override files are absent in the inspected installation. A new
    # one requires source review instead of silently changing the import roots.
    if (list(BASE_PYTHON.glob('*._pth')) or list(PYTHON.parent.glob('*._pth')) or list(VENV.glob('*._pth'))
            or (BASE_PYTHON / 'pyvenv.cfg').exists()):
        raise RuntimeError('unexpected base/venv Python path override')
    site = VENV / 'Lib/site-packages'
    pth = {p.name: p.read_text(encoding='utf-8').strip() for p in sorted(site.glob('*.pth'))}
    if pth != {
        '_virtualenv.pth': 'import _virtualenv',
        '__editable__.tire_intelligence_api-0.1.0.pth':
            'import __editable___tire_intelligence_api_0_1_0_finder; __editable___tire_intelligence_api_0_1_0_finder.install()',
    }:
        raise RuntimeError('unreviewed installed .pth startup/import roots')
    # literal_eval parses the inspected editable mapping without executing its
    # finder. Its transitive tire_api source is included by the source roots.
    finder = site / '__editable___tire_intelligence_api_0_1_0_finder.py'
    parsed = ast.parse(finder.read_text(encoding='utf-8'))
    assignments = {node.target.id: ast.literal_eval(node.value) for node in parsed.body
                   if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                   and node.target.id in ('MAPPING', 'NAMESPACES')}
    expected_mapping = {'tire_api': str(ROOT / 'apps/api/tire_api')}
    expected_namespaces = {'tire_api.assets': [str(ROOT / 'apps/api/tire_api/assets')],
                           'tire_api.assets.fonts': [str(ROOT / 'apps/api/tire_api/assets/fonts')]}
    if assignments.get('MAPPING') != expected_mapping or assignments.get('NAMESPACES') != expected_namespaces:
        raise RuntimeError('editable package mapping changed outside the bound project roots')
    excluded = (BASE_PYTHON / 'Lib/site-packages',)
    # The Windows import path includes the base root itself. Bind its complete
    # immediate shape, root modules and every existing directory as a possible
    # regular/namespace package, even when presently used only for docs/headers.
    base_children = {}
    for item in sorted(regular(BASE_PYTHON).iterdir()):
        regular(item)
        if item.is_file():
            base_children[item.name] = 'file'
        elif item.is_dir():
            base_children[item.name] = 'directory'
        else:
            raise RuntimeError('unsupported base CPython root entry: ' + str(item))
    base_directories = ('DLLs', 'Doc', 'Lib', 'Scripts', 'include', 'libs', 'share', 'tcl')
    if {name for name, kind in base_children.items() if kind == 'directory'} != set(base_directories):
        raise RuntimeError('unreviewed base CPython root directory shape')
    base_import_suffixes = ('.py', '.pyc', '.pyd')
    binary_roots = (BASE_PYTHON, PYTHON.parent, VENV)
    root_files = [p for folder in binary_roots for p in regular(folder).iterdir() if p.is_file()
                  and (p.suffix.lower() in ('.exe', '.dll', '.zip', '._pth') or p.name == 'pyvenv.cfg'
                       or (folder == BASE_PYTHON and p.suffix.lower() in base_import_suffixes))]
    if not {'python.exe', 'python312.dll', 'python3.dll'} <= {p.name for p in root_files if p.parent == BASE_PYTHON}:
        raise RuntimeError('actual base CPython exe/DLL inputs missing')
    roots = (*(BASE_PYTHON / name for name in base_directories), site)
    paths = [*root_files]
    for folder in roots:
        paths.extend(files(folder, excluded))
    return {'base_home': str(BASE_PYTHON), 'venv_site': str(site),
            'base_root_children': base_children,
            'base_root_import_suffixes': list(base_import_suffixes),
            'base_root_directory_scope': 'Every reviewed direct directory recursively hashed as a potential regular/namespace package; unknown directory shapes rejected.',
            'binary_roots': [str(p) for p in binary_roots],
            'root_binary_suffixes': ['.exe', '.dll', '.zip', '._pth'],
            'tree_roots': [str(p) for p in roots],
            'excluded_roots': [str(p) for p in excluded],
            'exclusion_basis': 'pyvenv include-system-site-packages=false, isolated -I, inspected installed .pth/finder; base global site-packages is not a configured import root',
            'files': manifest(paths), 'pth_configuration': pth,
            'scope_limit': 'Actual bounded runtime/package bytes and file-key sets only; no shared OS DLL/registry/loader or OS isolation guarantee.'}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def checked_json(path, sha):
    if not re.fullmatch(r'[a-f0-9]{64}', sha) or digest(path)['sha256'] != sha:
        raise RuntimeError('explicit independently reviewed input SHA required')
    return json.loads(path.read_text(encoding='utf-8'))


def env_files_absent():
    for base in (ROOT, ROOT / 'apps/web'):
        for name in ('.env', '.env.local', '.env.production', '.env.production.local'):
            if (base / name).exists():
                raise RuntimeError('ambient environment file forbidden')


def build_inputs(report_path, sha):
    if (report_path.name != 'verification.json' or report_path.parent.parent != ROOT / '.artifacts'
            or re.fullmatch(r'r98fb-[a-f0-9]{16}', report_path.parent.name) is None):
        raise RuntimeError('this round exact build report required')
    report = checked_json(report_path, sha)
    build_freeze = report_path.parent / 'freeze.json'
    build = checked_json(build_freeze, report['freeze_sha256'])
    if (report.get('schema') != 'r98-frontend-verification@1' or report.get('mode') != 'build'
            or report.get('state') != 'passed' or report.get('source_stable') is not True
            or report.get('generated_restore', {}).get('passed') is not True
            or build.get('api_base') != 'http://127.0.0.1:18986'):
        raise RuntimeError('passed exact source-stable build with restored generated files required')
    dist = ROOT / 'apps/web' / ('.next-r98-' + report_path.parent.name[-16:])
    artifact = report['artifacts']['web']
    if Path(build['web_dist']) != dist or Path(artifact['path']) != dist or not artifact.get('host_fingerprint_found'):
        raise RuntimeError('wrong current R98 Web artifact')
    actual = {p.relative_to(dist).as_posix(): digest(p) for p in files(dist)}
    if actual != artifact['files']:
        raise RuntimeError('complete build directory drift')
    for name, expected in report['source_after'].items():
        path = Path(name)
        if not path.is_relative_to(ROOT) or digest(path) != expected:
            raise RuntimeError('build/current source SHA mismatch: ' + name)
    return report, dist, build_freeze


def commands(output, private, dist):
    return {
        'api': [str(API_PYTHON), '-I', '-S', '-X', 'utf8', '-B', str(FIXTURE), '--output', str(private)],
        'web': [str(NODE), '--require', str(output / 'node-guard.cjs'), str(NEXT),
                'start', '--hostname', '127.0.0.1', '--port', str(WEB_PORT)],
    }


def environment(output, dist):
    allowed = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'SYSTEMDRIVE', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS'}
    value = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    value.update(PATH=str(NODE.parent) + os.pathsep + 'C:/Windows/System32', HOME=str(output / 'home'),
        USERPROFILE=str(output / 'home'), APPDATA=str(output / 'home/roam'), LOCALAPPDATA=str(output / 'home/local'),
        TEMP=str(output / 'tmp'), TMP=str(output / 'tmp'), TMPDIR=str(output / 'tmp'),
        NEXT_TELEMETRY_DISABLED='1', NODE_ENV='production', TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0',
        TI_OBSERVABILITY_ENABLED='0', TI_API_BASE_URL='http://127.0.0.1:18986', TI_NEXT_DIST_DIR=dist.name,
        R98_LAUNCH_OUTPUT=str(output), PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    return value


def freeze(output, private, report_path, report_sha):
    if output.exists() or private.exists():
        raise RuntimeError('fresh launcher output and separate fresh fixture output required')
    if digest(NODE) != NODE_PIN:
        raise RuntimeError('reviewed physical Node pin mismatch')
    if digest(API_PYTHON) != API_PYTHON_PIN:
        raise RuntimeError('reviewed direct base API Python pin mismatch')
    env_files_absent()
    report, dist, build_freeze = build_inputs(report_path, report_sha)
    source_paths = {SELF, SUPERVISOR, FIXTURE, QA, ROOT / 'apps/api/tests/test_vehicle_raw.py',
                    ROOT / 'apps/api/tests/admin_support.py', ROOT / 'package-lock.json',
                    ROOT / 'apps/web/next.config.ts', ROOT / 'apps/web/package.json',
                    ROOT / 'scripts/offline-host-build.mjs'}
    for folder in ('apps/api/tire_api', 'apps/web/app', 'apps/web/components', 'packages/api-client/src', 'packages/domain-types/src'):
        source_paths.update(p for p in files(ROOT / folder) if p.suffix in ('.py', '.ts', '.tsx', '.css', '.json'))
    source_paths.update(Path(p) for p in report['source_after'])
    tools = {PYTHON, API_PYTHON, NODE, CONSOLE, PYTHON.parent.parent / 'pyvenv.cfg', NEXT}
    dependency_roots = [ROOT / 'node_modules' / folder for folder in ('next', 'react', 'react-dom', '@next/swc-win32-x64-msvc')]
    dependencies = [p for folder in dependency_roots for p in files(folder)]
    python_inputs = python_installation()
    project_inputs = project_python_inputs()
    if digest(S2) != S2_PIN or digest(CONSOLE) != CONSOLE_PIN:
        raise RuntimeError('historical S2 or unique System32 console-helper pin mismatch')
    output.mkdir()
    for folder in ('home', 'home/roam', 'home/local', 'tmp'):
        (output / folder).mkdir(parents=True, exist_ok=True)
    preload = output / 'node-guard.cjs'
    preload.write_text(PRELOAD, encoding='utf-8')
    plan = {'schema': 'r98-private-web-launch-freeze@1', 'created': utc(), 'output': str(output),
        'private_output': str(private), 'build_report': str(report_path), 'build_report_sha256': report_sha,
        'sources': manifest(source_paths), 'tools': manifest(tools), 'next_dependencies': manifest(dependencies),
        'next_dependency_roots': [str(p) for p in dependency_roots],
        'next_dependency_scope': 'Exact listed Next/react/react-dom/SWC trees including file-key sets. Other installed Node packages/shared OS libraries are not claimed pinned by package-lock.',
        'python_installation': python_inputs,
        'project_python_inputs': project_inputs,
        'project_helper_scope': 'native supervisor helpers, raw/admin test helpers and tire_api tree; Next config -> offline-host-build.mjs -> literal inputs already present in build source_after. No helper executes during freeze.',
        'build_inputs': manifest([report_path, build_freeze]), 'dist': str(dist), 'dist_inputs': manifest(files(dist)),
        's2': S2_PIN, 'preload': digest(preload), 'argv': commands(output, private, dist),
        'cwd': {'api': str(ROOT), 'web': str(ROOT / 'apps/web')}, 'environment': environment(output, dist),
        'console_helper': {'path': str(CONSOLE), **CONSOLE_PIN, 'raw_commandlines': list(CONSOLE_ARGVS), 'max_per_tree': 1},
        'product_processes_per_tree': 1, 'max_duration_seconds': 3600,
        'scope': 'Private real HTTP/current React services only; no parser child/Provider/normal DB/real online adoption/device/OS save.'}
    write_json(output / 'freeze.json', plan)
    print(json.dumps({'frozen_not_run': True, 'output': str(output), 'freeze': digest(output / 'freeze.json')}))


def verify(plan):
    env_files_absent()
    for group in ('sources', 'tools', 'next_dependencies', 'build_inputs', 'dist_inputs'):
        if manifest(Path(p) for p in plan[group]) != plan[group]:
            raise RuntimeError('frozen ' + group + ' SHA drift')
    if manifest(p for folder in plan['next_dependency_roots'] for p in files(Path(folder))) != plan['next_dependencies']:
        raise RuntimeError('listed Next installation tree file-key set drift')
    if python_installation() != plan['python_installation']:
        raise RuntimeError('base CPython/venv actual runtime bytes, startup config or file-key set drift')
    if project_python_inputs() != plan['project_python_inputs']:
        raise RuntimeError('project Python source/bytecode/extension bytes or file-key set drift')
    if manifest(files(Path(plan['dist']))) != plan['dist_inputs'] or digest(S2) != plan['s2']:
        raise RuntimeError('complete build directory or S2 drift')
    if digest(Path(plan['output']) / 'node-guard.cjs') != plan['preload']:
        raise RuntimeError('Node guard drift')


def http(port, path, method='GET'):
    connection = http_client.HTTPConnection('127.0.0.1', port, timeout=2)
    try:
        connection.request(method, path, body=b'{}' if method == 'POST' else None,
                           headers={'Content-Type': 'application/json'} if method == 'POST' else {})
        response = connection.getresponse()
        value = response.read()
        return response.status, value
    finally:
        connection.close()


def run(output, reviewed_sha):
    plan = checked_json(output / 'freeze.json', reviewed_sha)
    private, dist = Path(plan['private_output']), Path(plan['dist'])
    regular(private)
    if (private.parent != ROOT / '.artifacts' or not re.fullmatch(r'r98w-[a-f0-9]{16}', private.name)
            or plan.get('schema') != 'r98-private-web-launch-freeze@1' or plan['output'] != str(output)
            or plan['argv'] != commands(output, private, dist) or private.exists()
            or (output / 'services.json').exists()):
        raise RuntimeError('single-use exact reviewed launcher freeze required')
    verify(plan)
    # Import only hash-bound stdlib-only Windows Job/process inspection helpers.
    spec = importlib.util.spec_from_file_location('r98_owned_job', SUPERVISOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    attempts = {'network_denied': 0, 'child_denied': 0, 'database_denied': 0}
    launches = []

    def audit(event, args):
        if event == 'subprocess.Popen':
            executable, argv, cwd, env = args
            name = ('api', 'web')[len(launches)] if len(launches) < 2 else None
            # CPython Windows audits the full list2cmdline string, not the input list.
            if (name and executable == plan['argv'][name][0] and isinstance(argv, str)
                    and argv == subprocess.list2cmdline(plan['argv'][name])
                    and cwd == plan['cwd'][name] and env == plan['environment']):
                launches.append(name)
                return
            attempts['child_denied'] += 1
            raise RuntimeError('unreviewed child forbidden')
        if event == 'socket.connect' and args[1] in (('127.0.0.1', API_PORT), ('127.0.0.1', WEB_PORT)):
            return
        if event == 'socket.getaddrinfo' and args[0] == '127.0.0.1' and args[1] in (API_PORT, WEB_PORT):
            return
        if event.startswith('socket.') and event not in ('socket.__new__',):
            attempts['network_denied'] += 1
            raise RuntimeError('launcher network outside exact loopback forbidden')
        if event in ('os.system', 'os.posix_spawn', 'os.startfile'):
            attempts['child_denied'] += 1
            raise RuntimeError('launcher child/OS launch forbidden')
        if event == 'sqlite3.connect':
            attempts['database_denied'] += 1
            raise RuntimeError('launcher never opens a database')

    sys.addaudithook(audit)
    stop = threading.Event()

    def commands_from_stdin():
        for line in sys.stdin:
            if line.strip() == 'stop':
                stop.set()
                return
        stop.set()  # Closed controlling input is a stop request, not orphaning.

    threading.Thread(target=commands_from_stdin, daemon=True).start()
    receipt = {'schema': 'r98-private-services@1', 'started': utc(), 'state': 'starting',
               'freeze_sha256': reviewed_sha, 'trees': {}, 'guard_counts': attempts,
               'foreign_processes_closed': 0, 'isolation_claim': 'Own Windows Jobs and API-level guards; not an OS network sandbox.'}
    children, handles, failure = {}, [], None

    def save():
        write_json(output / 'services.json', receipt)

    def observe(name):
        tree = receipt['trees'][name]
        job, process = children[name]
        seen = {tree['pid'], *(row['pid'] for row in tree['console_helpers'])}
        active = set(job.active())
        for pid in active - seen:
            row = module.process_identity(pid)
            valid = (Path(row['executable']) == CONSOLE and row['executable_input'] == CONSOLE_PIN
                     and row['commandline'] in CONSOLE_ARGVS and not tree['console_helpers'])
            row['allowed'] = valid
            tree['console_helpers'].append(row)
            save()
            if not valid:
                raise RuntimeError('unknown own descendant; product budget remains one')
        if len(active - {row['pid'] for row in tree['console_helpers']}) > 1:
            raise RuntimeError('product process cap exceeded')
        tree['exit_code'] = process.poll()

    save()
    try:
        # Read-only occupancy probes. An occupied port aborts; no listener owner is touched.
        for port in (API_PORT, WEB_PORT):
            with socket.socket() as probe:
                probe.settimeout(0.2)
                if probe.connect_ex(('127.0.0.1', port)) == 0:
                    raise RuntimeError('exact private port already occupied')
        for name in ('api', 'web'):
            stdout = (output / (name + '.stdout.log')).open('xb')
            stderr = (output / (name + '.stderr.log')).open('xb')
            handles.extend((stdout, stderr))
            job = module.PrivateJob(2)  # One product process plus at most one pinned console helper.
            try:
                process = subprocess.Popen(plan['argv'][name], executable=plan['argv'][name][0],
                    cwd=plan['cwd'][name], env=plan['environment'],
                    stdin=subprocess.PIPE if name == 'web' else subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                    creationflags=0x4 | subprocess.CREATE_NO_WINDOW, close_fds=True)
                children[name] = (job, process)
                receipt['trees'][name] = {'pid': process.pid, 'argv': plan['argv'][name], 'console_helpers': [],
                    'natural_shutdown_requested': False, 'natural_resources_closed': False,
                    'forced_own_job_cleanup': False, 'exit_code': None, 'product_process_cap': 1, 'console_helper_cap': 1}
                job.assign_resume(process)
            except BaseException:
                job.close()
                raise
            deadline = time.monotonic() + 120
            while True:
                for active_name in children:
                    observe(active_name)
                if process.poll() is not None or time.monotonic() > deadline or stop.is_set():
                    raise RuntimeError(name + ' exited, startup timed out, or stop requested before readiness')
                try:
                    status, _ = http(API_PORT if name == 'api' else WEB_PORT, '/fixture/state' if name == 'api' else '/')
                    if status == 200 and (name == 'web' or (private / 'started.json').is_file()):
                        receipt['trees'][name]['startup_http_status'] = status
                        break
                except OSError:
                    pass
                time.sleep(0.02)
            save()
        receipt['state'] = 'running'
        save()
        print(json.dumps({'ready': True, 'output': str(output), 'api_port': API_PORT, 'web_port': WEB_PORT}), flush=True)
        deadline = time.monotonic() + plan['max_duration_seconds']
        while not stop.wait(0.01):
            for name, (_, process) in children.items():
                observe(name)
                if process.poll() is not None:
                    raise RuntimeError(name + ' exited before requested shutdown')
            if time.monotonic() > deadline:
                raise TimeoutError('reviewed one-hour service budget exceeded')
    except KeyboardInterrupt:
        stop.set()
    except BaseException as error:
        failure = error
        receipt['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        # Request genuine application cleanup independently, even after startup failure.
        for name in ('web', 'api'):
            if name not in children:
                continue
            job, process = children[name]
            tree = receipt['trees'][name]
            try:
                if process.poll() is None:
                    if name == 'web':
                        process.stdin.write(b'stop\n')
                        process.stdin.flush()
                    else:
                        if tree.get('startup_http_status') != 200:
                            raise RuntimeError('own API never confirmed ready; no shutdown sent to an unowned listener')
                        status, _ = http(API_PORT, '/fixture/shutdown', 'POST')
                        if status != 200:
                            raise RuntimeError('own API shutdown not acknowledged')
                    tree['natural_shutdown_requested'] = True
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline and (process.poll() is None or job.active()):
                    observe(name)
                    time.sleep(0.01)
                tree['exit_code'] = process.poll()
                tree['active_after_natural_grace'] = job.active()
                tree['job_total_processes'] = job.total()
                tree['observed_processes'] = 1 + len(tree['console_helpers'])
                tree['all_processes_observed'] = tree['job_total_processes'] == tree['observed_processes']
                tree['natural_resources_closed'] = not tree['active_after_natural_grace'] and tree['exit_code'] == (143 if name == 'web' else 0)
                if not tree['natural_resources_closed'] or not tree['all_processes_observed']:
                    raise RuntimeError(name + ' natural exit/resource/process inventory incomplete')
            except BaseException as error:
                failure = failure or error
                tree['cleanup_error'] = type(error).__name__ + ': ' + str(error)
            finally:
                for resource, close in (
                    ('job', lambda: job.close()),
                    ('own_popen_kill_if_live', lambda: process.kill()),
                    ('process_wait', lambda: process.wait(timeout=10)),
                    ('stdin', lambda: process.stdin.close() if process.stdin is not None else None),
                ):
                    try:
                        if resource == 'job':
                            try:
                                tree['forced_own_job_cleanup'] = bool(job.active())
                            finally:
                                close()
                        elif resource == 'own_popen_kill_if_live':
                            tree['own_popen_kill_fallback'] = process.poll() is None
                            if tree['own_popen_kill_fallback']:
                                tree['natural_resources_closed'] = False
                                failure = failure or RuntimeError(name + ' required exact own Popen kill after Job cleanup')
                                close()  # Also covers a suspended child never assigned to its Job.
                        elif resource == 'process_wait':
                            tree['final_popen_exit_code'] = close()
                        else:
                            close()  # Only handles of this invocation's own new Job.
                    except BaseException as error:
                        failure = failure or error
                        tree.setdefault('resource_close_errors', []).append({'resource': resource, 'error': str(error)})
                save()
        for handle in handles:
            try:
                handle.close()
            except BaseException as error:
                failure = failure or error
                receipt.setdefault('log_close_errors', []).append(str(error))
        try:
            verify(plan)
            receipt['frozen_inputs_stable'] = True
        except BaseException as error:
            failure = failure or error
            receipt.setdefault('verification_error', str(error))
            receipt.setdefault('verification_errors', []).append({'stage': 'frozen_inputs', 'error': str(error)})
        try:
            if 'web' in children:
                logs = [json.loads(line) for line in (output / 'node-guard.jsonl').read_text(encoding='utf-8').splitlines()]
                receipt['node_guard_events'] = logs
                if (any(row['event'] == 'denied' for row in logs) or
                        not any(row['event'] == 'listener_closed' for row in logs) or
                        not any(row['event'] == 'exit' and row['code'] == 143 for row in logs)):
                    raise RuntimeError('Next guard deny/close/exit ledger incomplete')
            else:
                receipt['node_guard_verification'] = 'not_started'
        except BaseException as error:
            failure = failure or error
            receipt.setdefault('verification_error', str(error))
            receipt.setdefault('verification_errors', []).append({'stage': 'web_ledger', 'error': str(error)})
        try:
            if 'api' in children:
                api_return = json.loads((private / 'server-return.json').read_text(encoding='utf-8'))
                receipt['api_cleanup'] = api_return
                if not all(api_return.get(key) is True for key in ('startup_completed', 'original_lifespan_exit_returned',
                        'own_testclients_closed', 'engine_dispose_returned', 'policy_restored', 'own_listener_closed',
                        's2_unchanged', 'filesystem_clean')):
                    raise RuntimeError('API independent cleanup flags incomplete')
                if any(api_return.get('guard_counts', {}).get(key) != 0 for key in ('external_network_attempts',
                        'child_process_attempts', 'normal_database_attempts', 'filesystem_denied_attempts')):
                    raise RuntimeError('API guard deny ledger must remain zero')
            else:
                receipt['api_cleanup_verification'] = 'not_started'
        except BaseException as error:
            failure = failure or error
            receipt.setdefault('verification_error', str(error))
            receipt.setdefault('verification_errors', []).append({'stage': 'api_ledger', 'error': str(error)})
        if set(children) != {'api', 'web'} and failure is None:
            failure = RuntimeError('both owned services must start before a successful stop')
            receipt.setdefault('verification_error', str(failure))
            receipt.setdefault('verification_errors', []).append({'stage': 'startup', 'error': str(failure)})
        receipt['state'] = 'failed' if failure else 'stopped'
        receipt['ended'] = utc()
        receipt['private_outputs_retained'] = True
        save()
    return 1 if failure else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'run'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--private-output', type=Path)
    parser.add_argument('--build-report', type=Path)
    parser.add_argument('--build-report-sha256')
    parser.add_argument('--reviewed-freeze-sha256')
    args = parser.parse_args()
    if (Path(sys.executable).resolve() != PYTHON.resolve() or not sys.flags.isolated
            or not sys.flags.utf8_mode or not sys.dont_write_bytecode):
        raise RuntimeError('exact API Python -I -X utf8 -B required')
    output = regular(args.output.absolute())
    if output.parent != ROOT / '.artifacts' or not re.fullmatch(r'r98wl-[a-f0-9]{16}', output.name):
        raise RuntimeError('exact short private launcher output required')
    if args.action == 'run':
        if args.private_output or args.build_report or args.build_report_sha256 or not args.reviewed_freeze_sha256:
            raise RuntimeError('run only accepts exact output and reviewed freeze SHA')
        return run(output, args.reviewed_freeze_sha256)
    if not args.private_output or not args.build_report or not args.build_report_sha256 or args.reviewed_freeze_sha256:
        raise RuntimeError('freeze requires exact fresh fixture output, build report, reviewed build report SHA')
    private = regular(args.private_output.absolute())
    if private.parent != ROOT / '.artifacts' or not re.fullmatch(r'r98w-[a-f0-9]{16}', private.name):
        raise RuntimeError('exact fresh short fixture output required')
    freeze(output, private, regular(args.build_report.absolute()), args.build_report_sha256)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
