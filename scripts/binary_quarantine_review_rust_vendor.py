"""R98 V4 static candidate: freeze, then separately reviewed offline-local preparation.

Never invokes Cargo, a product module, a provider, or any child process. The only
archive authority is the complete authenticated d66f private archive directory.
No network requests or fallback are authorized by this version.
This is a fail-closed file preparer, not an OS/network sandbox or Rust acceptance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import re
import ssl
import stat
import sys
import tarfile
import threading
import time
import tomllib


ROOT = Path("E:/Mix/project/tire-info-manage-sys")
SELF = ROOT / "scripts/binary_quarantine_review_rust_vendor.py"
PYTHON = ROOT / "apps/api/.venv/Scripts/python.exe"
BASE = Path("D:/.PYENV/pyenv-win/versions/3.12.10")
LOCK = ROOT / "apps/desktop/src-tauri/Cargo.lock"
CACHE = ROOT / ".artifacts/r98rv-4c71a0e9b382d66f/archives"
LOCK_SHA = "7a33400029913f9f2994075a131be7744dc658b70e58fd4f63110553d0df9b8b"
SOURCE = "registry+https://github.com/rust-lang/crates.io-index"
# Historical V1/V2 authorities only; V3 denies every URL and never calls download.
DOWNLOADS = {
    "rsqlite-vfs-0.1.1": {
        "checksum": "c51c9ae4df8a7fba42103df5c621fa3c37eccf3a3c650879e90fc48b11cc192c",
        "url": "https://static.crates.io/crates/rsqlite-vfs/rsqlite-vfs-0.1.1.crate"},
    "sqlite-wasm-rs-0.5.5": {
        "checksum": "dc3efc0da82635d7e1ced0053bbbfa8c7ab9645d0bf36ceb4f7127bb85315d75",
        "url": "https://static.crates.io/crates/sqlite-wasm-rs/sqlite-wasm-rs-0.5.5.crate"},
}
POLICY = {
    "packages": 513, "max_archive_bytes": 32 * 1024 * 1024,
    "network_requests": 0, "max_network_bytes": 0, "network_seconds": 0,
    "socket_timeout_seconds": 15, "prepare_seconds": 1800,
    "max_package_tar_bytes": 256 * 1024 * 1024,
    "max_file_bytes": 128 * 1024 * 1024, "max_package_members": 50000,
    "max_vendor_bytes": 8 * 1024 * 1024 * 1024,
    "max_tar_metadata_read": 1024 * 1024, "chunk_bytes": 65536,
    "redirects": 0, "retries": 0, "children": 0,
    "source_cache_consumed": False, "credentials_or_proxies_inherited": False,
}


def fail(message: str):
    raise RuntimeError(message)


def checked(path: Path, kind: str | None = None):
    """Check every extant component, including junction/mount-point attributes."""
    if not path.is_absolute() or ".." in path.parts:
        fail("Absolute lexical path required: " + str(path))
    for component in reversed((path, *path.parents)):
        try:
            info = component.lstat()
        except FileNotFoundError:
            if component == path and kind is None:
                return None
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            fail("Symlink/reparse point forbidden: " + str(component))
        if component != path and not stat.S_ISDIR(info.st_mode):
            fail("Non-directory ancestor: " + str(component))
    if kind == "file" and not stat.S_ISREG(info.st_mode):
        fail("Regular file required: " + str(path))
    if kind == "dir" and not stat.S_ISDIR(info.st_mode):
        fail("Regular directory required: " + str(path))
    return info


def digest(path: Path, ceiling: int = POLICY["max_file_bytes"]) -> dict:
    before = checked(path, "file")
    if before.st_size > ceiling:
        fail("File exceeds bound: " + str(path))
    total, result = 0, hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(POLICY["chunk_bytes"]):
            total += len(data)
            if total > ceiling:
                fail("File grew past bound: " + str(path))
            result.update(data)
    after = checked(path, "file")
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if identity(before) != identity(after) or total != before.st_size:
        fail("Input changed during read: " + str(path))
    return {"bytes": total, "sha256": result.hexdigest()}


def files(root: Path, runtime=False) -> list[Path]:
    checked(root, "dir")
    result = []
    for child in sorted(root.iterdir()):
        info = checked(child)
        if runtime and child == BASE / "Lib/site-packages":
            continue
        if stat.S_ISDIR(info.st_mode):
            result.extend(files(child, runtime))
        elif stat.S_ISREG(info.st_mode):
            result.append(child)
        else:
            fail("Unsupported input: " + str(child))
    return result


def directories(root: Path) -> list[str]:
    result = []
    checked(root, "dir")
    for child in sorted(root.iterdir()):
        info = checked(child)
        if stat.S_ISDIR(info.st_mode):
            result.append(child.relative_to(root).as_posix())
            result.extend(child.name + "/" + item for item in directories(child))
        elif not stat.S_ISREG(info.st_mode):
            fail("Unsupported private entry: " + str(child))
    return sorted(result)


def manifest(paths) -> dict:
    return {str(path): digest(path) for path in sorted(set(paths))}


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii")


def write_new(path: Path, data: bytes):
    checked(path.parent, "dir")
    if checked(path) is not None:
        fail("Refuse overwrite: " + str(path))
    with path.open("xb") as stream:
        stream.write(data)
    checked(path, "file")


def new_dir(path: Path):
    checked(path.parent, "dir")
    if checked(path) is not None:
        fail("Fresh directory required: " + str(path))
    path.mkdir()
    checked(path, "dir")


def mkdir_inside(path: Path, boundary: Path):
    if not path.is_relative_to(boundary):
        fail("Private boundary violation")
    for component in (*reversed(path.relative_to(boundary).parents), path.relative_to(boundary)):
        target = boundary / component
        if checked(target) is None:
            target.mkdir()
        checked(target, "dir")


def output_path(raw: str) -> Path:
    path = Path(raw)
    if path.parent != ROOT / ".artifacts" or not re.fullmatch(r"r98rv-[0-9a-f]{16}", path.name):
        fail("Exact absolute .artifacts/r98rv-<16 lowercase hex> output required")
    checked(path.parent, "dir")
    checked(path)
    return path


def bootstrap():
    if os.name != "nt" or sys.version_info[:3] != (3, 12, 10):
        fail("Exact Windows CPython 3.12.10 required")
    if Path(sys.executable) != PYTHON or Path(sys.base_prefix) != BASE or Path(__file__).absolute() != SELF:
        fail("Exact isolated venv interpreter, base and script paths required")
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode and sys.flags.utf8_mode):
        fail("Required literal Python flags: -I -S -X utf8 -B")
    checked(SELF, "file")
    # No .netrc, proxy, SSL_CERT_FILE, provider, HOME or credential inheritance.
    os.environ.clear()
    os.environ.update(SystemRoot="C:\\Windows", WINDIR="C:\\Windows")
    def deny_children(event, args):
        if event in {"subprocess.Popen", "os.system", "os.fork", "os.posix_spawn", "os.startfile"} or event.startswith(("os.exec", "os.spawn")):
            fail("Child process creation forbidden")
    sys.addaudithook(deny_children)


def snapshot(output: Path) -> dict:
    lock_record = digest(LOCK)
    if lock_record["sha256"] != LOCK_SHA:
        fail("Current Cargo.lock differs from reviewed R98 lock")
    packages = []
    names = set()
    for package in tomllib.loads(LOCK.read_text(encoding="utf-8"))["package"]:
        if "source" not in package:
            continue
        if package["source"] != SOURCE:
            fail("Unreviewed registry/git dependency source")
        name, version, checksum = (package[key] for key in ("name", "version", "checksum"))
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or not re.fullmatch(r"[A-Za-z0-9.+-]+", version) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            fail("Invalid locked package identity")
        key = name + "-" + version
        if key.casefold() in names:
            fail("Duplicate/Windows-aliased package identity")
        names.add(key.casefold())
        archive = CACHE / (key + ".crate")
        record = digest(archive, POLICY["max_archive_bytes"]) if checked(archive) is not None else None
        if record is None:
            fail("Missing authenticated private archive; no network fallback: " + key)
        elif record["sha256"] != checksum:
            fail("Existing archive differs from Cargo.lock: " + key)
        packages.append({"name": name, "version": version, "key": key, "checksum": checksum,
                         "archive": str(archive), "frozen_archive": record,
                         "download_url": None})
    if len(packages) != POLICY["packages"] or any(package["download_url"] is not None for package in packages):
        fail("Complete offline 513-package closure with no URL required")
    tools = [PYTHON, PYTHON.parent.parent / "pyvenv.cfg"]
    tools += [path for path in BASE.iterdir() if path.suffix.lower() in {".exe", ".dll"}]
    tools += files(BASE / "DLLs", runtime=True) + files(BASE / "Lib", runtime=True)
    return {"schema": "r98-rust-offline-vendor-freeze@1", "output": str(output), "root": str(ROOT),
            "policy": POLICY, "sources": manifest([SELF, LOCK]), "runtime": manifest(tools),
            "packages": sorted(packages, key=lambda item: item["key"]),
            "runtime_exclusions": [str(BASE / "Lib/site-packages")],
            "scope": "All 513 authenticated private registry archives; offline-local preparation only; no Cargo or Rust tests."}


def freeze(output: Path):
    if checked(output) is not None:
        fail("Freeze requires fresh private output")
    plan = snapshot(output)
    new_dir(output)
    write_new(output / "freeze.json", json_bytes(plan))
    print(json.dumps({"output": str(output), "freeze": digest(output / "freeze.json")}))


def copy_archive(source: Path, target: Path, expected: dict):
    if digest(source, POLICY["max_archive_bytes"]) != expected:
        fail("Archive drift before copy")
    checked(target.parent, "dir")
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        total = 0
        while data := incoming.read(POLICY["chunk_bytes"]):
            total += len(data)
            if total > POLICY["max_archive_bytes"]:
                fail("Archive copy exceeds bound")
            outgoing.write(data)
    if digest(target, POLICY["max_archive_bytes"]) != expected or digest(source, POLICY["max_archive_bytes"]) != expected:
        fail("Archive drift during copy")


def download(package: dict, target: Path, network: dict, deadline: float):
    fail("Network disabled in V3 offline-local preparer")
    authority = DOWNLOADS.get(package["key"])
    if authority is None or package["download_url"] != authority["url"] or package["checksum"] != authority["checksum"]:
        fail("Download authority mismatch")
    expected_url = authority["url"]
    context = ssl.create_default_context()  # OS trust store; environment was cleared.
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = http.client.HTTPSConnection("static.crates.io", port=443,
                                             timeout=POLICY["socket_timeout_seconds"], context=context)
    started, total = time.monotonic(), 0
    attempt = {"key": package["key"], "url": expected_url, "method": "GET", "status": None,
               "actual_body_bytes": 0, "lock_sha256": package["checksum"], "completed": False}
    network["attempts"].append(attempt)
    try:
        connection.request("GET", expected_url.removeprefix("https://static.crates.io"),
                           headers={"Accept-Encoding": "identity", "Connection": "close", "User-Agent": "r98-public-source-preparer/1"})
        response = connection.getresponse()
        attempt["status"] = response.status
        if response.status != 200:  # Includes all redirects; never follow/retry.
            fail("Exact public archive GET returned status " + str(response.status))
        lengths = response.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0]):
            fail("Single bounded Content-Length required")
        length = int(lengths[0])
        if not 0 < length <= POLICY["max_archive_bytes"] or response.getheader("Transfer-Encoding") or response.getheader("Content-Encoding", "identity") != "identity":
            fail("Unsupported archive transfer framing/encoding/size")
        with target.open("xb") as outgoing:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    fail("Global network wall-clock budget exhausted")
                if connection.sock is not None:
                    connection.sock.settimeout(min(POLICY["socket_timeout_seconds"], remaining))
                data = response.read(min(POLICY["chunk_bytes"], length - total + 1))
                if not data:
                    break
                total += len(data)
                attempt["actual_body_bytes"] += len(data)
                network["actual_body_bytes"] += len(data)
                if total > length or network["actual_body_bytes"] > POLICY["max_network_bytes"]:
                    fail("Archive/network byte budget exhausted")
                outgoing.write(data)
        if total != length:
            fail("Incomplete archive response")
        record = digest(target, POLICY["max_archive_bytes"])
        if record["sha256"] != package["checksum"]:
            fail("Downloaded archive differs from Cargo.lock")
        network["completed"].append({"key": package["key"], "url": expected_url, "method": "GET",
                                     "status": 200, **record, "elapsed_seconds": round(time.monotonic() - started, 3)})
        attempt["completed"] = True
    finally:
        attempt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        connection.close()


class BoundedTar(io.BufferedReader):
    def read(self, size=-1):
        if not 0 <= size <= POLICY["max_tar_metadata_read"]:
            fail("Unbounded/oversized tar metadata read")
        return super().read(size)


def safe_parts(member: tarfile.TarInfo, key: str) -> tuple[str, ...]:
    name = member.name
    if member.type == tarfile.DIRTYPE and name.endswith("/"):
        name = name[:-1]
    # Locked schemars versions' long snapshot names; never a general 8.3 alias exception.
    known_snapshot = re.fullmatch(
        r"^schemars-(?:0\.9\.0|1\.2\.2)/tests/integration/snapshots/schemars/tests/integration/[A-Za-z0-9_.-]+\.rs~[A-Za-z0-9_.-]+\.json$", name)
    if len(name) > 512 or not re.fullmatch(r"[ -~]+", name) or "\\" in name or ("~" in name and not known_snapshot):
        fail("Non-ASCII, Windows short-name alias or invalid archive path")
    parts = tuple(name.split("/"))
    if len(parts) > 24 or parts[0] != key:
        fail("Archive path outside exact package root")
    for part in parts:
        if not part or part in {".", ".."} or part != part.rstrip(" .") or part.startswith(" ") or re.search(r'[<>:"\\|?*]', part):
            fail("Unsafe Windows path component")
        if re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?", part, flags=re.IGNORECASE):
            fail("Windows reserved device alias")
    return parts[1:]


def extract(package: dict, archive: Path, vendor: Path, scratch: Path, usage: dict) -> dict:
    # Verify the complete compressed bytes against Cargo.lock before gzip/tar sees them.
    archive_record = digest(archive, POLICY["max_archive_bytes"])
    if archive_record["sha256"] != package["checksum"]:
        fail("Archive lock checksum mismatch before tar parsing")
    unpacked = scratch / (package["key"] + ".tar")
    tar_bytes = 0
    with gzip.open(archive, "rb") as source, unpacked.open("xb") as target:
        while data := source.read(POLICY["chunk_bytes"]):
            tar_bytes += len(data)
            if tar_bytes > POLICY["max_package_tar_bytes"]:
                fail("Expanded tar bound exceeded")
            target.write(data)
    package_root = vendor / package["key"]
    new_dir(package_root)
    explicit, claimed, file_records = set(), {}, {}
    member_count = 0
    with BoundedTar(unpacked.open("rb", buffering=0)) as raw, tarfile.open(fileobj=raw, mode="r:") as tar:
        for member in tar:
            member_count += 1
            if member_count > POLICY["max_package_members"] or member.type not in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE} or member.issparse():
                fail("Too many, linked, device, sparse or unsupported tar members")
            if not 0 <= member.size <= POLICY["max_file_bytes"] or member.linkname:
                fail("Invalid member payload/link")
            parts = safe_parts(member, package["key"])
            key = "/".join(parts)
            if key.casefold() in explicit:
                fail("Duplicate archive entry")
            explicit.add(key.casefold())
            directory = member.type == tarfile.DIRTYPE
            if not parts and not directory:
                fail("Package root must be a directory")
            for count in range(1, len(parts) + 1):
                spelling = "/".join(parts[:count])
                kind = "dir" if count < len(parts) or directory else "file"
                previous = claimed.setdefault(spelling.casefold(), (spelling, kind))
                if previous != (spelling, kind):
                    fail("Windows case alias or file/directory collision")
            target = package_root.joinpath(*parts)
            if directory:
                if member.size:
                    fail("Directory with payload rejected")
                mkdir_inside(target, package_root)
                continue
            mkdir_inside(target.parent, package_root)
            stream = tar.extractfile(member)
            if stream is None:
                fail("Regular member stream missing")
            sha, count = hashlib.sha256(), 0
            with stream, target.open("xb") as outgoing:
                while data := stream.read(POLICY["chunk_bytes"]):
                    count += len(data)
                    usage["bytes"] += len(data)
                    if count > member.size or usage["bytes"] > POLICY["max_vendor_bytes"]:
                        fail("Private vendor byte budget exceeded")
                    sha.update(data)
                    outgoing.write(data)
            if count != member.size:
                fail("Short member payload")
            file_records[key] = {"bytes": count, "sha256": sha.hexdigest()}
        # Require complete tar end markers and only zero padding after them.
        raw.seek(tar.offset)
        tail_bytes = 0
        while data := raw.read(POLICY["chunk_bytes"]):
            tail_bytes += len(data)
            if any(data):
                fail("Nonzero content after tar end")
        if tail_bytes < 1024:
            fail("Two tar EOF blocks required")
    if "Cargo.toml" not in file_records:
        fail("Complete package Cargo.toml missing")
    checksum_path = package_root / ".cargo-checksum.json"
    expected_checksum = {"package": package["checksum"], "files": {key: value["sha256"] for key, value in file_records.items() if key != ".cargo-checksum.json"}}
    generated = ".cargo-checksum.json" not in file_records
    if generated:
        write_new(checksum_path, json_bytes(expected_checksum))
        usage["bytes"] += checked(checksum_path, "file").st_size
        if usage["bytes"] > POLICY["max_vendor_bytes"]:
            fail("Generated checksum exceeds private vendor byte budget")
    elif json.loads(checksum_path.read_text(encoding="utf-8")) != expected_checksum:
        fail("Archived Cargo directory-source checksum manifest differs from extracted files/lock")
    file_records[".cargo-checksum.json"] = digest(checksum_path)
    actual = {path.relative_to(package_root).as_posix(): digest(path) for path in files(package_root)}
    if actual != file_records:
        fail("Private package bytes/keyset changed during extraction")
    if digest(archive, POLICY["max_archive_bytes"]) != archive_record:
        fail("Private archive drift during extraction")
    checked(unpacked, "file")
    unpacked.unlink()  # This invocation's one private scratch file only.
    return {"key": package["key"], "checksum": package["checksum"], "archive": archive_record,
            "origin": "exact-public-download" if package["download_url"] else "frozen-local-lock-matched-archive",
            "source_path": package["download_url"] or package["archive"],
            "tar_bytes": tar_bytes, "cargo_checksum_generated": generated,
            "directories": directories(package_root), "files": file_records}


def prepare(output: Path, reviewed_sha: str):
    checked(output, "dir")
    if {item.name for item in output.iterdir()} != {"freeze.json"}:
        fail("Prepare requires untouched freeze-only output; failed runs are never resumed")
    if not re.fullmatch(r"[0-9a-f]{64}", reviewed_sha) or digest(output / "freeze.json")["sha256"] != reviewed_sha:
        fail("Explicit independently reviewed freeze SHA-256 required")
    plan = json.loads((output / "freeze.json").read_text(encoding="ascii"))
    if POLICY["network_requests"] != 0 or any(package["download_url"] is not None or package["frozen_archive"] is None for package in plan["packages"]):
        fail("V3 prepare requires every private archive and zero URL/network authority")
    if plan != snapshot(output):
        fail("Freeze/source/runtime/archive/keyset drift")
    watchdog = threading.Timer(POLICY["prepare_seconds"], lambda: os._exit(98))
    watchdog.daemon = True
    watchdog.start()
    network = {"actual_body_bytes": 0, "attempts": [], "completed": [], "retries": 0, "redirects": 0}
    try:
        for name in ("archives", "vendor", "scratch"):
            new_dir(output / name)
        for package in plan["packages"]:
            if package["frozen_archive"] is not None:
                copy_archive(Path(package["archive"]), output / "archives" / (package["key"] + ".crate"), package["frozen_archive"])
        # Offline V3 writes only a zero receipt; no network watchdog or download call.
        write_new(output / "download-receipt.json", json_bytes(network))
        usage, packages = {"bytes": 0}, []
        for package in plan["packages"]:
            packages.append(extract(package, output / "archives" / (package["key"] + ".crate"), output / "vendor", output / "scratch", usage))
        if plan != snapshot(output):
            fail("Frozen offline inputs changed during prepare")
        private_files = {path.relative_to(output / "vendor").as_posix(): digest(path) for path in files(output / "vendor")}
        expected_files = {package["key"] + "/" + key: value for package in packages for key, value in package["files"].items()}
        private_directories = directories(output / "vendor")
        expected_directories = sorted(directory for package in packages
                                      for directory in [package["key"], *[package["key"] + "/" + item for item in package["directories"]]])
        if private_files != expected_files or private_directories != expected_directories:
            fail("Final vendor keyset/bytes mismatch")
        config = '[net]\noffline = true\n[source.crates-io]\nreplace-with = "r98-private-vendor"\n[source.r98-private-vendor]\ndirectory = ' + json.dumps((output / "vendor").as_posix()) + '\n'
        write_new(output / "vendor-config.toml", config.encode("ascii"))
        write_new(output / "prepared.json", json_bytes({
            "schema": "r98-rust-offline-vendor-prepared@1", "completed_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_freeze_sha256": reviewed_sha, "output": str(output), "packages": packages,
            "network": network, "vendor_files": private_files,
            "vendor_directories": private_directories,
            "vendor_config": digest(output / "vendor-config.toml"),
            "scope": "Offline-local dependency preparation only; historical public GETs accounted separately; no Cargo/build/test/product/provider/device acceptance.",
            "shared_cache_writes": False, "native_verifier_changed": False, "rust_tests_started": False}))
        print(json.dumps({"prepared": digest(output / "prepared.json"), "packages": len(packages), "network_bytes": network["actual_body_bytes"]}))
    finally:
        watchdog.cancel()


def main():
    bootstrap()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "prepare"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--reviewed-freeze-sha256")
    args = parser.parse_args()
    output = output_path(args.output)
    if args.phase == "freeze":
        if args.reviewed_freeze_sha256 is not None:
            fail("Freeze accepts no reviewed hash")
        freeze(output)
    else:
        prepare(output, args.reviewed_freeze_sha256 or "")


if __name__ == "__main__":
    main()
