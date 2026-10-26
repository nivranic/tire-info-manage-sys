"""R98 exact, offline candidates. Freeze/run only after new independent review.

No old wrapper, pin or permission is reused. This is not an OS/network sandbox.
The private Windows Job owns only processes created by this invocation.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
PYTHON = ROOT / "apps/api/.venv/Scripts/python.exe"
NODE = Path("C:/Program Files/nodejs/node.exe")
FRONTEND_NEXT_NODE_PHYSICAL = Path("E:/DevTools/nvm/v22.22.1/node.exe")
FRONTEND_NEXT_NODE_INPUT = {"bytes": 87059456, "sha256": "923a41f268ab49ede2e3363fbdd9e790609e385c6f3ca880b4ee9a56a8133e5a"}
CONSOLE = Path("C:/Windows/System32/conhost.exe")
CONSOLE_POLICY = {"executable": str(CONSOLE), "bytes": 1003520,
                  "sha256": "c86146188b78e484f32cc29e2331689659943b47689a85570342044f499938ac",
                  "raw_commandline": r"\??\C:\WINDOWS\system32\conhost.exe 0xffffffff -ForceV1", "max_per_phase": 1}
FRONTEND_NEXT_CONSOLE_POLICY = {
    "schema": "r98-frontend-next-console-policy@1", "executable": str(CONSOLE),
    "bytes": CONSOLE_POLICY["bytes"], "sha256": CONSOLE_POLICY["sha256"],
    "raw_commandlines": [CONSOLE_POLICY["raw_commandline"], r"\??\C:\WINDOWS\system32\conhost.exe 0x4"],
    "max_per_phase": 48, "product_process_cap": 48, "job_process_cap": 96,
    "ownership_scope": "Aggregate console budget only; no per-Node parent attribution",
}
RUST = Path("E:/DevTools/rustup/toolchains/1.95.0-x86_64-pc-windows-msvc/bin")
RUST_LLD = Path("E:/DevTools/rustup/toolchains/1.95.0-x86_64-pc-windows-msvc/lib/rustlib/x86_64-pc-windows-msvc/bin/rust-lld.exe")
RUST_LLD_INPUT = {"bytes": 113349120, "sha256": "3cf499fc8a03853722d19e3ae1c5cdd143ac7426f1405b9e6efacd7a94b7328a"}
MSVC = Path("C:/Program Files (x86)/Microsoft Visual Studio/2019/BuildTools/VC/Tools/MSVC/14.29.30133")
SDK = Path("C:/Program Files (x86)/Windows Kits/10")
SDK_VERSION = "10.0.26100.0"
RUST_VENDOR = ROOT / ".artifacts/r98rv-4c71a0e9b382d68f"
REGISTRY = RUST_VENDOR / "vendor"
RUST_VENDOR_PINS = {
    RUST_VENDOR / "prepared.json": "da9a4d837dcd8c5c049a74ba9f6ea8a175605ce56ba86e457cf591db0d67ada7",
    RUST_VENDOR / "freeze.json": "db8eba5deb8d9906b101d21bc74d1243b45feedf6e696cbcee91495332d6ccde",
    RUST_VENDOR / "vendor-config.toml": "4e92e3cd743c80903cb87e43e318d5fcf301c1506403215f0f61d3f81b84d432",
}
RUST_VENDOR_LOCK_SHA = "7a33400029913f9f2994075a131be7744dc658b70e58fd4f63110553d0df9b8b"
JDK = Path("D:/JAVA_21/bin")
JAVA = ROOT / "apps/mobile/android/app/src/main/java/org/taiji/tireintelligence/mobile"
JAVA_TEST = ROOT / "apps/mobile/android/app/src/test/java/org/taiji/tireintelligence/mobile"
JARS = [ROOT / ".artifacts/mobile/gradle/caches/modules-2/files-2.1" / suffix for suffix in (
    "junit/junit/4.13.2/8ac9e16d933b6fb43bc7f576336b8f4d7eb5ba12/junit-4.13.2.jar",
    "org.hamcrest/hamcrest-core/1.3/42a25dc3219429f0e5d060061f71acb49bf010a0/hamcrest-core-1.3.jar")]
RUST_TESTS = (
    "launch_config_accepts_only_a_port_and_isolated_slug",
    "path_rejects_url_normalization_and_encoded_bypasses",
    "headers_do_not_allow_credentials_authority_or_arbitrary_controls",
    "inventory_hint_is_limited_to_canonical_get_routes_and_ascii_account_ids",
    "inventory_hint_does_not_expand_other_routes_methods_or_credential_headers",
    "inventory_hint_preserves_header_budget_and_get_body_rejection",
    "quarantine_review_hint_accepts_exact_post_and_preserves_json_bytes",
    "quarantine_review_hint_rejects_raw_path_and_query_aliases",
    "quarantine_review_hint_rejects_bad_ids_duplicates_credentials_and_fourth_header",
    "quarantine_review_hint_preserves_missing_header_and_existing_body_rules",
    "metadata_is_bounded_json_and_request_body_has_real_byte_limit",
    "native_download_and_external_link_validation",
    "privileged_webview_navigation_remains_local",
    "ipc_shapes_reject_extra_authority_and_status_never_serializes_a_cookie",
)
JAVA_CLASSES = (
    "org.taiji.tireintelligence.mobile.NativePolicyInventoryTest",
    "org.taiji.tireintelligence.mobile.NativePolicyQuarantineReviewTest",
)


def digest(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Nonregular or missing input: " + str(path))
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def frontend_next_policy(output: Path) -> dict:
    preload = str(output / "r98-preload.cjs")
    worker = str(ROOT / "node_modules/next/dist/compiled/jest-worker/processChild.js")
    return {"schema": "r98-frontend-next-policy@1", "node_lexical": str(NODE),
            "node_physical": str(FRONTEND_NEXT_NODE_PHYSICAL), "executable_input": FRONTEND_NEXT_NODE_INPUT,
            "preload": preload, "worker": worker, "exec_argv_variants": [[], ["--enable-source-maps"]],
            "worker_args": [], "argv_variants": [[str(NODE), "--require", preload, worker],
                                                   [str(NODE), "--require", preload, "--enable-source-maps", worker]],
            "path_equivalence": "Windows slash/case only"}


def frontend_next_typescript_cli_policy(output: Path) -> dict:
    preload, cwd = str(output / "r98-preload.cjs"), str(ROOT / "apps/web")
    tsc, config = str(ROOT / "node_modules/typescript/bin/tsc"), str(ROOT / "apps/web/tsconfig.json")
    web_dist = ROOT / "apps/web" / (".next-r98-" + output.name[-16:])
    roles = [
        {"role": "next-ts-show-config", "request_args": [tsc, "--showConfig", "--project", config, "--pretty", "false"], "path_request_indices": [0, 3]},
        {"role": "next-ts-typecheck", "request_args": [tsc, "--project", config, "--noEmit", "--declarationMap", "false", "--emitDeclarationOnly", "false", "--tsBuildInfoFile", str(web_dist / "cache/.tsbuildinfo")], "path_request_indices": [0, 2, 9]},
    ]
    for role in roles:
        role["actual_argv"] = [str(NODE), "--require", preload, *role["request_args"]]
        role["path_argv_indices"] = [0, 2, *[index + 3 for index in role["path_request_indices"]]]
    return {"schema": "r98-frontend-next-typescript-cli-policy@1", "node_lexical": str(NODE),
            "node_physical": str(FRONTEND_NEXT_NODE_PHYSICAL), "executable_input": FRONTEND_NEXT_NODE_INPUT,
            "cwd": cwd, "options": {"own_keys": ["cwd", "detached", "env", "shell", "stdio"], "detached": False,
                                     "shell": False, "stdio": ["ignore", "pipe", "pipe"],
                                     "env_contract": "Exact shallow copy of current process.env; values never audited"},
            "roles": roles, "repetition": "No exact invocation count asserted; existing phase time/process/console limits remain"}


def tree(path: Path) -> list[Path]:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError("Missing/nonregular input directory: " + str(path))
    result = []
    for entry in sorted(path.iterdir()):
        if entry.is_symlink():
            raise RuntimeError("Symlink/reparse input: " + str(entry))
        if entry.is_dir():
            result.extend(tree(entry))
        elif entry.is_file():
            result.append(entry)
        else:
            raise RuntimeError("Unsupported input: " + str(entry))
    return result


def manifest(paths) -> dict:
    return {str(p.resolve()): digest(p) for p in sorted(set(paths))}


def reviewed_rust_vendor() -> dict:
    for path, expected_sha in RUST_VENDOR_PINS.items():
        if digest(path)["sha256"] != expected_sha:
            raise RuntimeError("Reviewed private Rust vendor receipt/config drift")
    prepared = json.loads((RUST_VENDOR / "prepared.json").read_text(encoding="utf-8"))
    if (prepared.get("schema") != "r98-rust-offline-vendor-prepared@1" or
            prepared.get("output") != str(RUST_VENDOR) or
            prepared.get("reviewed_freeze_sha256") != RUST_VENDOR_PINS[RUST_VENDOR / "freeze.json"] or
            prepared.get("vendor_config", {}).get("sha256") != RUST_VENDOR_PINS[RUST_VENDOR / "vendor-config.toml"] or
            prepared.get("network") != {"actual_body_bytes": 0, "attempts": [], "completed": [], "retries": 0, "redirects": 0} or
            len(prepared.get("packages", [])) != 513 or len(prepared.get("vendor_files", {})) != 27914 or
            len(prepared.get("vendor_directories", [])) != 5562 or
            digest(ROOT / "apps/desktop/src-tauri/Cargo.lock")["sha256"] != RUST_VENDOR_LOCK_SHA):
        raise RuntimeError("Exact prepared vendor provenance, offline ledger and Cargo.lock required")
    return prepared


def rust_vendor_tree(prepared: dict) -> list[Path]:
    files, directories = [], []

    def visit(directory: Path) -> None:
        if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
            raise RuntimeError("Missing/nonregular private Rust vendor directory: " + str(directory))
        for entry in sorted(directory.iterdir()):
            if entry.is_symlink() or entry.is_junction():
                raise RuntimeError("Symlink/junction in private Rust vendor: " + str(entry))
            if entry.is_dir():
                directories.append(entry.relative_to(REGISTRY).as_posix())
                visit(entry)
            elif entry.is_file():
                files.append(entry)
            else:
                raise RuntimeError("Unsupported private Rust vendor input: " + str(entry))

    visit(REGISTRY)
    if sorted(directories) != prepared["vendor_directories"]:
        raise RuntimeError("Complete private Rust vendor directory keyset drift")
    return files


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def output_path(raw: str, kind: str, fresh=False) -> Path:
    output = Path(raw).resolve()
    prefix = {"rust": "r98nr", "java": "r98nj", "checks": "r98fc", "build": "r98fb"}[kind]
    if output.parent != ROOT / ".artifacts" or not re.fullmatch(prefix + r"-[0-9a-f]{16}", output.name):
        raise RuntimeError("Exact short private output required")
    if output.is_symlink() or (fresh and output.exists()):
        raise RuntimeError("Fresh non-symlink private output required")
    return output


def clean_environment(output: Path, kind: str | None = None) -> dict:
    # An allowlist prevents unanticipated provider/secret/proxy variables from inheritance.
    permitted = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "SYSTEMDRIVE"}
    env = {k: v for k, v in os.environ.items() if k.upper() in permitted}
    private_home = output / "home"
    env.update(PATH=";".join(str(p) for p in (RUST, MSVC / "bin/Hostx64/x64", SDK / "bin" / SDK_VERSION / "x64", Path("C:/Windows/System32"))),
               HOME=str(private_home), USERPROFILE=str(private_home), APPDATA=str(private_home / "AppData/Roaming"),
               LOCALAPPDATA=str(private_home / "AppData/Local"), TEMP=str(output / "tmp"), TMP=str(output / "tmp"), TMPDIR=str(output / "tmp"),
               CARGO_HOME=str(output / "cargo-home"), CARGO_NET_OFFLINE="true", CARGO_INCREMENTAL="0",
               RUSTUP_HOME="E:/DevTools/rustup", RUSTUP_TOOLCHAIN="1.95.0-x86_64-pc-windows-msvc",
               RUSTC=str(RUST / "rustc.exe"), RUSTDOC=str(RUST / "rustdoc.exe"), JAVA_HOME="D:/JAVA_21",
               CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER=str(MSVC / "bin/Hostx64/x64/link.exe"),
               INCLUDE=";".join(str(p) for p in (MSVC / "include", SDK / "Include" / SDK_VERSION / "ucrt", SDK / "Include" / SDK_VERSION / "shared", SDK / "Include" / SDK_VERSION / "um", SDK / "Include" / SDK_VERSION / "winrt")),
               LIB=";".join(str(p) for p in (MSVC / "lib/x64", SDK / "Lib" / SDK_VERSION / "ucrt/x64", SDK / "Lib" / SDK_VERSION / "um/x64")),
               VCToolsInstallDir=str(MSVC) + "/", WindowsSdkDir=str(SDK) + "/", WindowsSDKVersion=SDK_VERSION + "/", VSCMD_ARG_TGT_ARCH="x64",
               CI="1", NEXT_TELEMETRY_DISABLED="1")
    if kind == "rust":
        env.update(CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER=str(RUST_LLD), CARGO_ENCODED_RUSTFLAGS="-Clinker-flavor=lld-link", CARGO_BUILD_JOBS="1")
    return env


def native_plan(output: Path, kind: str) -> dict:
    host = ROOT / "apps/desktop/src-tauri"
    common = [SELF, ROOT / "scripts/binary_quarantine_review_frontend_verify.mjs"]
    source_roots, dependency_roots = [], []
    if kind == "java":
        sources = [JAVA / "NativeFailure.java", JAVA / "NativePolicy.java", JAVA_TEST / "NativePolicyInventoryTest.java", JAVA_TEST / "NativePolicyQuarantineReviewTest.java"]
        # Bind production host wiring as context, without claiming it is compiled by JVM policy checks.
        sources += [JAVA / n for n in ("TireNativePlugin.java", "NativeHttpBridge.java", "OfflineRuntime.java")]
        classes = output / "jc"
        cp = os.pathsep.join(str(p) for p in JARS)
        phases = [{"name": "javac-policy", "argv": [str(JDK / "javac.exe"), "-encoding", "UTF-8", "-proc:none", "-cp", cp, "-d", str(classes), *[str(p) for p in sources[:4]]], "cwd": str(ROOT), "timeout_seconds": 180, "descendants": "none"},
                  {"name": "junit-policy", "argv": [str(JDK / "java.exe"), "-cp", str(classes) + os.pathsep + cp, "org.junit.runner.JUnitCore", *JAVA_CLASSES], "cwd": str(ROOT), "timeout_seconds": 180, "descendants": "none"}]
        dependencies = JARS
        tools = [PYTHON, JDK / "java.exe", JDK / "javac.exe", CONSOLE]
    else:
        prepared = reviewed_rust_vendor()
        source_roots = [host / folder for folder in ("src", "capabilities", "icons", "tests")]
        sources = [host / n for n in ("Cargo.toml", "Cargo.lock", "build.rs", "tauri.conf.json")]
        sources += [p for folder in ("src", "capabilities", "icons", "tests") for p in tree(host / folder)]
        sources += [ROOT / "packages/domain-types/src/query-filter-unicode.json"]
        sources += sorted((ROOT / "apps/api/tests/data").glob("query-filters49*.json"))
        lock = tomllib.loads((host / "Cargo.lock").read_text(encoding="utf-8"))
        dependencies = list(RUST_VENDOR_PINS)
        for package in lock["package"]:
            if "source" not in package:
                continue
            if package["source"] != "registry+https://github.com/rust-lang/crates.io-index":
                raise RuntimeError("Unreviewed Rust dependency source")
        dependency_roots = [REGISTRY]  # Bind the entire vendor keyset, including any unexpected package.
        dependencies += rust_vendor_tree(prepared)
        snapshot_manifest = output / "src/apps/desktop/src-tauri/Cargo.toml"
        phases = [{"name": "rust-" + name, "argv": [str(RUST / "cargo.exe"), "test", "--lib", "--locked", "--offline", "--manifest-path", str(snapshot_manifest), "--target-dir", str(output / "rt"), "security_tests::" + name, "--", "--exact", "--test-threads=1"], "cwd": str(snapshot_manifest.parent), "timeout_seconds": 1800, "descendants": "rust-toolchain"} for name in RUST_TESTS]
        tools = [PYTHON, RUST / "cargo.exe", RUST / "rustc.exe", RUST / "rustdoc.exe", CONSOLE, RUST_LLD]
        tools += [p for p in (MSVC / "bin/Hostx64/x64" / n for n in ("cl.exe", "link.exe", "lib.exe", "cvtres.exe", "mspdbsrv.exe")) if p.exists()]
        tools += [p for p in (SDK / "bin" / SDK_VERSION / "x64" / n for n in ("rc.exe", "mt.exe")) if p.exists()]
    return {"schema": "r98-exact-native-freeze@1", "kind": kind, "output": str(output), "frozen_at": utc(),
            "sources": manifest(sources + common), "dependencies": manifest(dependencies), "executables": manifest(tools), "phases": phases,
            "source_roots": [str(p) for p in source_roots], "dependency_roots": [str(p) for p in dependency_roots], "console_helper": CONSOLE_POLICY,
            "scope": "Real Rust host lib snapshot, exact security unit targets; no Tauri UI/picker/device." if kind == "rust" else "Pure production Java policy and JUnit: inventory 5 + review 5; no Android Plugin/HTTP/device compilation or acceptance."}


def verify_inputs(plan: dict, dependencies=False, during_build=False) -> None:
    if plan.get("console_helper") != CONSOLE_POLICY or digest(CONSOLE) != {"bytes": CONSOLE_POLICY["bytes"], "sha256": CONSOLE_POLICY["sha256"]}:
        raise RuntimeError("Exact native System32 console-helper policy/hash required")
    if plan.get("kind") == "rust":
        if plan["executables"].get(str(RUST_LLD)) != RUST_LLD_INPUT or digest(RUST_LLD) != RUST_LLD_INPUT:
            raise RuntimeError("Exact reviewed Rust LLD path/bytes/hash required")
        prepared = reviewed_rust_vendor()
        expected_vendor = {str(REGISTRY / name): record for name, record in prepared["vendor_files"].items()}
        frozen_vendor = {name: record for name, record in plan["dependencies"].items() if Path(name).is_relative_to(REGISTRY)}
        if (plan.get("dependency_roots") != [str(REGISTRY)] or frozen_vendor != expected_vendor or
                any(plan["dependencies"].get(str(path), {}).get("sha256") != pin for path, pin in RUST_VENDOR_PINS.items())):
            raise RuntimeError("Complete private vendor bytes/keyset and all three receipt/config pins required")
    if plan.get("kind") == "build":
        policy = frontend_next_policy(Path(plan["output"]))
        if (plan.get("frontend_next_console_policy") != FRONTEND_NEXT_CONSOLE_POLICY or
                plan.get("frontend_next_typescript_cli_policy") != frontend_next_typescript_cli_policy(Path(plan["output"])) or
                plan.get("frontend_next_policy") != policy or NODE.resolve() != FRONTEND_NEXT_NODE_PHYSICAL or
                digest(NODE) != FRONTEND_NEXT_NODE_INPUT or digest(FRONTEND_NEXT_NODE_PHYSICAL) != FRONTEND_NEXT_NODE_INPUT or
                any(plan["executables"].get(str(path)) != FRONTEND_NEXT_NODE_INPUT for path in (NODE, FRONTEND_NEXT_NODE_PHYSICAL))):
            raise RuntimeError("Fixed frontend-next lexical/physical Node policy and equal hash pins required")
    mutable_build_source = str(ROOT / "apps/web/tsconfig.json")
    allow_build_tsconfig = during_build and plan.get("kind") == "build"
    if allow_build_tsconfig:
        records = [r for r in plan.get("generated_before", {}).get("records", []) if r["path"] == mutable_build_source]
        expected = plan["sources"].get(mutable_build_source)
        if len(records) != 1 or not records[0].get("exists") or {k: records[0][k] for k in ("bytes", "sha256")} != expected or plan["generated_inputs"].get(records[0].get("backup")) != expected:
            raise RuntimeError("Build-only tsconfig must retain its complete original source pin and before backup")
    sections = ("sources", "executables", "generated_inputs") + (("dependencies",) if dependencies else ())
    for section in sections:
        for name, expected in plan.get(section, {}).items():
            if allow_build_tsconfig and section == "sources" and name == mutable_build_source:
                continue
            if digest(Path(name)) != expected:
                raise RuntimeError("Frozen input drift: " + name)
    for key, section in (("source_roots", "sources"), ("dependency_roots", "dependencies")):
        if section == "dependencies" and not dependencies:
            continue
        for raw_root in plan.get(key, []):
            directory = Path(raw_root)
            frozen = {name for name in plan[section] if Path(name).is_relative_to(directory)}
            live_files = rust_vendor_tree(prepared) if plan.get("kind") == "rust" and section == "dependencies" else tree(directory)
            if {str(p.resolve()) for p in live_files} != frozen:
                raise RuntimeError("Frozen input keyset drift: " + raw_root)


def read_freeze(output: Path, expected_sha: str, during_build=False) -> dict:
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha) or digest(output / "freeze.json")["sha256"] != expected_sha:
        raise RuntimeError("Independently reviewed freeze SHA required")
    plan = json.loads((output / "freeze.json").read_text(encoding="utf-8"))
    if Path(plan["output"]) != output or plan["sources"].get(str(SELF)) != digest(SELF):
        raise RuntimeError("Wrong output or supervisor source pin")
    verify_inputs(plan, dependencies=True, during_build=during_build)
    return plan


class PrivateJob:
    """A kill-on-close job, assigned before its own suspended child can run."""
    def __init__(self, max_processes: int):
        if os.name != "nt":
            raise RuntimeError("This reviewed candidate requires Windows")
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k.CreateJobObjectW.restype = wintypes.HANDLE
        self.k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.k.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        self.k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.k.CloseHandle.argtypes = [wintypes.HANDLE]
        class Basic(ctypes.Structure):
            _fields_ = [("ProcessUserTimeLimit", ctypes.c_int64), ("JobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
        class Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        self.handle = self.k.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x8  # kill on job close, active process cap; no breakaway.
        limits.BasicLimitInformation.ActiveProcessLimit = max_processes
        if not self.k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def assign_resume(self, process) -> None:
        if not self.k.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):
            process.kill()
            raise ctypes.WinError(ctypes.get_last_error())
        ntdll = ctypes.WinDLL("ntdll")
        ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
        ntdll.NtResumeProcess.restype = ctypes.c_long
        if ntdll.NtResumeProcess(wintypes.HANDLE(int(process._handle))) != 0:
            self.k.TerminateJobObject(self.handle, 98)
            raise RuntimeError("Could not resume owned suspended child")

    def active(self) -> list[int]:
        # JOBOBJECT_BASIC_PROCESS_ID_LIST, with room above the reviewed 96-process maximum.
        count = 128
        buffer = ctypes.create_string_buffer(8 + ctypes.sizeof(ctypes.c_size_t) * count)
        if not self.k.QueryInformationJobObject(self.handle, 3, buffer, len(buffer), None):
            raise ctypes.WinError(ctypes.get_last_error())
        number = wintypes.DWORD.from_buffer(buffer, 4).value
        return list((ctypes.c_size_t * number).from_buffer(buffer, 8))

    def total(self) -> int:
        buffer = ctypes.create_string_buffer(48)
        if not self.k.QueryInformationJobObject(self.handle, 1, buffer, len(buffer), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return wintypes.DWORD.from_buffer(buffer, 36).value

    def close(self) -> None:
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


def process_identity(pid: int) -> dict:
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    handle = k.OpenProcess(0x1000 | 0x10, False, pid)
    if not handle:
        raise RuntimeError("Owned process disappeared before identity observation: " + str(pid))
    try:
        size = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if not k.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        ntdll = ctypes.WinDLL("ntdll")
        ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        ntdll.NtQueryInformationProcess.restype = ctypes.c_long
        needed = wintypes.ULONG()
        ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(needed))
        if not 0 < needed.value < 131072:
            raise RuntimeError("Unreadable owned process command line")
        buffer = ctypes.create_string_buffer(needed.value)
        if ntdll.NtQueryInformationProcess(handle, 60, buffer, len(buffer), ctypes.byref(needed)) != 0:
            raise RuntimeError("Owned process command line unavailable")
        class UnicodeString(ctypes.Structure):
            _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]
        raw = UnicodeString.from_buffer(buffer)
        commandline = ctypes.wstring_at(raw.Buffer, raw.Length // 2)
        return {"pid": pid, "executable": str(Path(image.value).resolve()), "executable_input": digest(Path(image.value)), "commandline": commandline, "observed_at": utc()}
    finally:
        k.CloseHandle(handle)


def windows_argv(commandline: str) -> list[str]:
    if not commandline or "\x00" in commandline:
        raise RuntimeError("Empty/NUL owned process command line")
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    parsed = shell.CommandLineToArgvW(commandline, ctypes.byref(count))
    if not parsed:
        raise RuntimeError("Owned process Windows argv unavailable")
    try:
        return [parsed[index] for index in range(count.value)]
    finally:
        kernel.LocalFree(ctypes.cast(parsed, wintypes.HLOCAL))


def same_windows_path(actual: str, expected: str) -> bool:
    # No resolve/normpath: relative, dot segments, suffixes and extra arguments stay rejected.
    return actual.replace("/", "\\").lower() == expected.replace("/", "\\").lower()


def allowed_descendant(record: dict, phase: dict, plan: dict, output: Path) -> bool:
    executable = Path(record["executable"])
    if phase["descendants"] == "frontend-next":
        policy = frontend_next_policy(output)
        if (plan.get("kind") != "build" or plan.get("frontend_next_policy") != policy or
                not same_windows_path(str(executable), str(FRONTEND_NEXT_NODE_PHYSICAL)) or
                record.get("executable_input") != FRONTEND_NEXT_NODE_INPUT):
            return False
        argv = windows_argv(record["commandline"])
        worker_match = any(len(argv) == len(expected) and all(
            same_windows_path(actual, literal) if index in (0, 2, len(expected) - 1) else actual == literal
            for index, (actual, literal) in enumerate(zip(argv, expected))) for expected in policy["argv_variants"])
        if worker_match:
            record["role"] = "next-worker"
            return True
        cli_policy = frontend_next_typescript_cli_policy(output)
        if plan.get("frontend_next_typescript_cli_policy") != cli_policy:
            return False
        for role in cli_policy["roles"]:
            expected = role["actual_argv"]
            if len(argv) == len(expected) and all(
                    same_windows_path(actual, literal) if index in role["path_argv_indices"] else actual == literal
                    for index, (actual, literal) in enumerate(zip(argv, expected))):
                record["role"] = role["role"]
                return True
        return False
    if phase["descendants"] != "rust-toolchain":
        return False
    if executable == RUST_LLD:
        return (plan.get("kind") == "rust" and plan["executables"].get(str(RUST_LLD)) == RUST_LLD_INPUT and
                record.get("executable_input") == RUST_LLD_INPUT)
    if str(executable) in plan["executables"]:
        return executable.name.lower() in {"rustc.exe", "rustdoc.exe", "cargo.exe", "cl.exe", "link.exe", "lib.exe", "cvtres.exe", "rc.exe", "mt.exe", "mspdbsrv.exe"}
    # Cargo's generated binaries stay in the fresh target directory; bind their bytes on first observation.
    try:
        local = executable.relative_to(output / "rt/debug")
    except ValueError:
        return False
    return (bool(re.fullmatch(r"build/[^/]+/build-script-(?:build|main)\.exe", local.as_posix())) or
            bool(re.fullmatch(r"deps/tire_desktop_lib-[a-f0-9]+\.exe", local.as_posix())))


def phase_console_policy(phase: dict, plan: dict) -> dict:
    if phase["descendants"] == "frontend-next":
        if phase["name"] != "web-next" or plan.get("kind") != "build" or plan.get("frontend_next_console_policy") != FRONTEND_NEXT_CONSOLE_POLICY:
            raise RuntimeError("Exact build web-next console policy required")
        return FRONTEND_NEXT_CONSOLE_POLICY
    return CONSOLE_POLICY


def supervise(output: Path, phase: dict, plan: dict, env: dict, during_build=False) -> dict:
    name = phase["name"]
    receipt = output / (name + ".process.json")
    record = {"name": name, "argv": phase["argv"], "cwd": phase["cwd"], "timeout_seconds": phase["timeout_seconds"], "started": utc(), "exit_code": None, "state": "running", "children": [], "console_helpers": [], "natural_resources_closed": False, "limits_backend": "private_windows_job_object", "isolation_claim": "Own process tree cleanup only; not an OS/network permission boundary."}
    write_json(receipt, record)
    job, process, failure, seen = None, None, None, set()
    try:
        verify_inputs(plan, during_build=during_build)
        product_cap = 48 if phase["descendants"] != "none" else 1
        console_policy = phase_console_policy(phase, plan)
        console_cap = console_policy["max_per_phase"]
        console_commands = console_policy["raw_commandlines"] if "raw_commandlines" in console_policy else [console_policy["raw_commandline"]]
        record["product_process_cap"] = product_cap
        record["console_helper_cap"] = console_cap
        record["console_policy"] = console_policy
        record["job_process_cap"] = product_cap + console_cap
        job = PrivateJob(product_cap + console_cap)
        with (output / (name + ".stdout.log")).open("xb") as stdout, (output / (name + ".stderr.log")).open("xb") as stderr:
            phase_env = {**env, **({"R98_PHASE_NAME": name} if during_build else {})}
            if during_build:
                record["controlled_environment_delta"] = {"R98_PHASE_NAME": name}
            process = subprocess.Popen(phase["argv"], cwd=phase["cwd"], env=phase_env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       creationflags=0x4 | subprocess.CREATE_NO_WINDOW, close_fds=True)  # CREATE_SUSPENDED
            record["pid"] = process.pid
            seen = {process.pid}
            record["executable_input"] = digest(Path(phase["argv"][0]))
            job.assign_resume(process)
            deadline = time.monotonic() + phase["timeout_seconds"]
            grace_deadline = None
            while True:
                now = time.monotonic()
                root_returncode = process.poll()
                if root_returncode is None and now > deadline:
                    raise TimeoutError(name + " exceeded the reviewed wall budget")
                if root_returncode is not None and grace_deadline is None:
                    record["root_exit_observed_at"] = utc()
                    grace_deadline = now + 5  # Fixed once; new children never extend natural grace.
                    write_json(receipt, record)
                observation_phase = "root-running" if root_returncode is None else "natural-grace"
                active = set(job.active())
                for pid in active - seen:
                    child = process_identity(pid)
                    child["observation_phase"] = observation_phase
                    seen.add(pid)
                    if Path(child["executable"]) == CONSOLE:
                        record["console_helpers"].append(child)
                        child["allowed"] = (len(record["console_helpers"]) <= console_cap and child["commandline"] in console_commands and
                                            child["executable_input"] == {"bytes": console_policy["bytes"], "sha256": console_policy["sha256"]})
                    else:
                        record["children"].append(child)
                        child["allowed"] = allowed_descendant(child, phase, plan, output)
                    write_json(receipt, record)
                    if not child["allowed"]:
                        raise RuntimeError("Unreviewed descendant; private job will close")
                helper_ids = {r["pid"] for r in record["console_helpers"]}
                if len(active - helper_ids) > product_cap:
                    raise RuntimeError("Original product process budget exceeded")
                if root_returncode is not None:
                    if not active:
                        break
                    if time.monotonic() >= grace_deadline:
                        raise TimeoutError(name + " exceeded the fixed natural grace after root exit")
                time.sleep(0.005 if root_returncode is None else 0.02)
            record["exit_code"] = process.wait(timeout=5)
            # Never force leftover workers closed and then report a naturally clean success.
            record["active_pids_after_natural_grace"] = job.active()
            record["job_total_processes"] = job.total()
            record["observed_processes"] = len(seen)
            record["all_processes_observed"] = job.total() == len(seen)
            record["natural_resources_closed"] = not record["active_pids_after_natural_grace"]
            if record["exit_code"] != 0 or not record["natural_resources_closed"] or not record["all_processes_observed"]:
                raise RuntimeError(name + " exit/resource/process inventory failed")
            stdout_text = (output / (name + ".stdout.log")).read_text(encoding="utf-8", errors="replace")
            if name.startswith("rust-"):
                expected = "security_tests::" + name.removeprefix("rust-")
                actual = re.findall(r"^test (\S+) \.\.\. ok\s*$", stdout_text, re.MULTILINE)
                if actual != [expected] or not re.search(r"test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; \d+ filtered out", stdout_text):
                    raise RuntimeError("Rust exact test name/count mismatch (including zero-test runs)")
                record["test_result"] = {"expected": [expected], "actual": actual, "passed": 1}
            elif name == "junit-policy":
                if not re.search(r"^OK \(10 tests\)\s*$", stdout_text, re.MULTILINE):
                    raise RuntimeError("Expected actual JUnit count: inventory 5 + review 5")
                record["test_result"] = {"expected_classes": list(JAVA_CLASSES), "actual_passed": 10}
            elif "expected_tap_tests" in phase:
                expected = phase["expected_tap_tests"]
                counts = {key: [int(n) for n in re.findall(r"^# " + key + r" (\d+)\s*$", stdout_text, re.MULTILINE)] for key in ("tests", "pass", "fail", "cancelled", "skipped", "todo")}
                if counts != {"tests": [expected], "pass": [expected], "fail": [0], "cancelled": [0], "skipped": [0], "todo": [0]}:
                    raise RuntimeError("Node actual TAP counts differ from the frozen exact expectation")
                record["test_result"] = {"expected_tests": expected, "actual_tap_counts": counts}
            elif phase.get("evidence_kind"):
                record["test_result"] = {"kind": phase["evidence_kind"], "entry_exit_code": record["exit_code"]}
            verify_inputs(plan, during_build=during_build)
            record["state"] = "passed"
    except BaseException as error:
        failure = error
        record["state"] = "failed"
        record["error"] = type(error).__name__ + ": " + str(error)
    finally:
        if job:
            try:
                record["forced_job_close"] = bool(job.active())
            except BaseException as error:
                record["cleanup_query_error"] = str(error)
                record["state"] = "failed"
                failure = failure or error
            finally:
                job.close()
        if process:
            try:
                # A failure between Popen(CREATE_SUSPENDED) and assignment (including
                # executable hashing/API exceptions) leaves an owned child outside
                # the Job. Terminate that exact Popen handle as a separate fallback.
                # The direct child has already naturally exited on every success.
                if process.poll() is None:
                    record["owned_popen_termination_requested"] = True
                    record["state"] = "failed"
                    failure = failure or RuntimeError("Owned Popen still alive after Job closure")
                    process.kill()
                record["final_exit_code"] = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                record["cleanup_error"] = "Owned process did not finish after private job close"
                record["state"] = "failed"
                failure = failure or RuntimeError(record["cleanup_error"])
            except BaseException as error:
                record["cleanup_error"] = type(error).__name__ + ": " + str(error)
                record["state"] = "failed"
                failure = failure or error
        classified = ([record["pid"]] if "pid" in record else []) + [child["pid"] for child in record["children"]] + [helper["pid"] for helper in record["console_helpers"]]
        record["observed_processes"] = len(seen)
        record["observed_product_processes"] = (1 if "pid" in record else 0) + len(record["children"])
        record["observed_console_helpers"] = len(record["console_helpers"])
        record["classified_observed_pids"] = sorted(classified)
        record["all_observed_classified"] = len(classified) == len(seen) and set(classified) == seen
        if not record["all_observed_classified"]:
            record["state"] = "failed"
            record["classification_error"] = "Owned observed process classification mismatch"
            failure = failure or RuntimeError(record["classification_error"])
        record["ended"] = utc()
        write_json(receipt, record)
    if failure:
        raise RuntimeError(record.get("error", record.get("cleanup_error", "Owned job cleanup failed")))
    return record


def freeze_native(kind: str, output: Path) -> None:
    plan = native_plan(output, kind)  # Hash all live inputs before creating any output.
    verify_inputs(plan)
    output.mkdir()
    for name in ("tmp", "home", "home/AppData/Local", "home/AppData/Roaming", "cargo-home", "jc"):
        (output / name).mkdir(parents=True, exist_ok=True)
    generated = []
    if kind == "rust":
        for source in plan["sources"]:
            src = Path(source)
            if src in (SELF, ROOT / "scripts/binary_quarantine_review_frontend_verify.mjs"):
                continue
            target = output / "src" / src.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            generated.append(target)
        config = output / "cargo-home/config.toml"
        shutil.copyfile(RUST_VENDOR / "vendor-config.toml", config)
        generated.append(config)
    plan["generated_inputs"] = manifest(generated)
    plan["environment"] = clean_environment(output, kind=kind)
    verify_inputs(plan)
    write_json(output / "freeze.json", plan)
    print(json.dumps({"state": "frozen-not-run", "output": str(output), "freeze": digest(output / "freeze.json")}, ensure_ascii=False))


def main() -> int:
    if Path(sys.executable).resolve() != PYTHON.resolve() or not sys.flags.isolated or not sys.dont_write_bytecode or not sys.flags.utf8_mode:
        raise RuntimeError("Reviewed isolated venv Python (-I -X utf8 -B) required")
    if len(sys.argv) == 5 and sys.argv[1] == "frontend-phase":
        output = Path(sys.argv[2]).resolve()
        plan = read_freeze(output, sys.argv[4], during_build=True)
        if plan["kind"] not in ("checks", "build") or output_path(str(output), plan["kind"]) != output:
            raise RuntimeError("Wrong frontend freeze kind")
        phases = [p for p in plan["phases"] if p["name"] == sys.argv[3]]
        if len(phases) != 1 or Path(phases[0]["argv"][0]) != NODE:
            raise RuntimeError("Exactly one frozen Node phase required")
        supervise(output, phases[0], plan, plan["environment"], during_build=plan["kind"] == "build")
        return 0
    if len(sys.argv) not in (4, 5) or sys.argv[1] not in ("freeze", "run") or sys.argv[2] not in ("rust", "java"):
        raise RuntimeError("Usage: isolated-python candidate.py freeze rust|java fresh-output OR run rust|java frozen-output reviewed-freeze-sha256")
    action, kind = sys.argv[1:3]
    output = output_path(sys.argv[3], kind, fresh=action == "freeze")
    if action == "freeze":
        if len(sys.argv) != 4:
            raise RuntimeError("No extra freeze arguments")
        freeze_native(kind, output)
        return 0
    if len(sys.argv) != 5 or (output / "verification.json").exists():
        raise RuntimeError("Reviewed freeze SHA and unused frozen output required")
    plan = read_freeze(output, sys.argv[4])
    if plan["kind"] != kind:
        raise RuntimeError("Mode differs from reviewed freeze")
    report = {"schema": "r98-native-verification@1", "kind": kind, "state": "running", "started": utc(), "freeze_sha256": sys.argv[4], "scope": plan["scope"], "phases": []}
    write_json(output / "verification.json", report)
    failure = None
    try:
        for phase in plan["phases"]:
            report["phases"].append(supervise(output, phase, plan, plan["environment"]))
            write_json(output / "verification.json", report)
        report["state"] = "passed"
    except BaseException as error:
        failure = error
        report["state"] = "failed"
        report["error"] = type(error).__name__ + ": " + str(error)
    finally:
        try:
            verify_inputs(plan, dependencies=True)
            report["source_dependency_executable_snapshot_stable"] = True
            report["sources_after"] = manifest(Path(p) for p in plan["sources"])
            report["executables_after"] = manifest(Path(p) for p in plan["executables"])
            report["dependencies_after"] = manifest(Path(p) for p in plan.get("dependencies", {}))
        except BaseException as error:
            failure = failure or error
            report["state"] = "failed"
            report["source_dependency_executable_snapshot_stable"] = False
            report["after_error"] = str(error)
        report["ended"] = utc()
        report["retained_outputs"] = True
        write_json(output / "verification.json", report)
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
