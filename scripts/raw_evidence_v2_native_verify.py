"""R96 exact offline production authority checks; no app/API/provider/database/device startup."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NODE = Path('C:/Program Files/nodejs/node.exe')
CARGO = Path('E:/DevTools/cargo/bin/cargo.exe')
JDK = Path('D:/JAVA_21/bin')
MODES = ('rust', 'java', 'rust-host', 'rust-host-test')


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in MODES:
        raise SystemExit('Usage: isolated-python raw_evidence_v2_native_verify.py rust|java|rust-host|rust-host-test fresh-output')
    mode, output = sys.argv[1], Path(sys.argv[2]).resolve()
    if output.parent != (ROOT / '.artifacts').resolve() or not re.fullmatch(r'r96-native-[a-f0-9]{32}', output.name) or output.exists():
        raise SystemExit('Fresh private r96-native-GUID output required')
    output.mkdir()
    temporary = output / 'tmp'
    temporary.mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('TI_', 'TIRE_', 'OPENAI_', 'ANTHROPIC_', 'AZURE_OPENAI_', 'OTEL_', 'SENTRY_'))
           and k.upper() not in {'DATABASE_URL', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'NODE_OPTIONS', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS'}}
    env.update(RUSTUP_HOME='E:/DevTools/rustup', CARGO_HOME='E:/DevTools/cargo',
               RUSTUP_TOOLCHAIN='1.95.0-x86_64-pc-windows-msvc', CARGO_NET_OFFLINE='true',
               CARGO_TARGET_DIR=str(output / 'rust-target'), JAVA_HOME='D:/JAVA_21',
               TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))
    rust_root = ROOT / 'apps/desktop/src-tauri'
    java_root = ROOT / 'apps/mobile/android/app/src/main/java/org/taiji/tireintelligence/mobile'
    native_tests = ROOT / 'apps/mobile/native-tests'
    if mode == 'rust':
        inputs = [rust_root / 'src/download_authority.rs', *sorted((rust_root / 'src/download_authority').rglob('*.rs')), rust_root / 'Cargo.toml', rust_root / 'Cargo.lock']
    elif mode == 'java':
        inputs = [java_root / name for name in ('NativeFailure.java', 'NativePolicy.java', 'RequestRegistry.java', 'SessionState.java', 'DownloadAuthority.java', 'DownloadJob.java')]
        inputs += [native_tests / name for name in ('NativeCoreTest.java', 'DownloadAuthorityTest.java', 'DownloadJobTest.java')]
    else:
        inputs = [p for name in ('src', 'capabilities', 'icons') for p in (rust_root / name).rglob('*') if p.is_file()]
        inputs += [rust_root / name for name in ('Cargo.toml', 'Cargo.lock', 'build.rs', 'tauri.conf.json')]
        inputs += [ROOT / 'packages/domain-types/src/query-filter-unicode.json']
        if mode == 'rust-host-test':
            inputs += [ROOT / 'apps/api/tests/data' / name for name in ('query-filters49.json', 'query-filters49-extra.json')]
            inputs += [rust_root / 'tests/support' / name for name in ('device_ai_corpus.rs', 'device_ai_capacity_corpus.rs')]
    # Bind the live host wiring even for pure checks; compilation scope stays explicit below.
    inputs += [java_root / name for name in ('TireNativePlugin.java', 'NativeHttpBridge.java', 'OfflineRuntime.java')]
    inputs += [rust_root / 'src/lib.rs', rust_root / 'src/bridge.rs', Path(__file__).resolve()]
    inputs = sorted(set(inputs))

    def sources():
        return {p.relative_to(ROOT).as_posix(): {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in inputs}

    report = {'schema': 'r96-native@1', 'mode': mode, 'state': 'running',
              'sources_before': sources(), 'sources_after': None, 'sources_stable': None,
              'phases': [], 'generated_inputs': [],
              'scope': ('Current production Rust lib/bridge compile only; no Tauri picker/WebView2/device acceptance.' if mode == 'rust-host' else
                        'Current production Rust lib/bridge plus exactly two Bridge identity-admission tests; no Tauri picker/WebView2/device acceptance.' if mode == 'rust-host-test' else
                        'Current production pure modules compiled/executed; does not compile Rust lib/bridge or Java Plugin/HttpBridge; no host/device acceptance.')}

    def save():
        (output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def generated(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        report['generated_inputs'].append({'path': str(path), 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})

    def run(name, argv, cwd=ROOT):
        if sources() != report['sources_before']:
            raise RuntimeError('Source drift before ' + name)
        record = {'name': name, 'argv': [str(a) for a in argv], 'cwd': str(cwd), 'started': datetime.now(timezone.utc).isoformat(), 'exit_code': None}
        executable = Path(argv[0])
        record['executable_sha256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
        report['phases'].append(record)
        save()
        with (output / (name + '.stdout.log')).open('wb') as stdout, (output / (name + '.stderr.log')).open('wb') as stderr:
            try:
                result = subprocess.run(record['argv'], cwd=cwd, env=env, stdout=stdout, stderr=stderr, timeout=1800)
                record['exit_code'] = result.returncode
            except Exception as error:
                record['spawn_error'] = type(error).__name__ + ': ' + str(error)
                raise
            finally:
                record['ended'] = datetime.now(timezone.utc).isoformat()
                save()
        print(json.dumps(record), flush=True)
        if record['exit_code'] != 0:
            raise RuntimeError(name + ' failed')

    save()
    failure = None
    try:
        if mode == 'rust':
            harness = output / 'rust-authority'
            generated(harness / 'Cargo.toml', '[package]\nname="r96-download-authority"\nversion="0.0.0"\nedition="2021"\n[workspace]\n[dependencies]\nuuid={version="1",features=["v4"]}\npercent-encoding="=2.3.2"\n')
            generated(harness / 'src/lib.rs', '#[path="' + (rust_root / 'src/download_authority.rs').as_posix() + '"]\nmod download_authority;\n')
            save()
            run('cargo-authority', [CARGO, 'test', '--offline', '--manifest-path', harness / 'Cargo.toml', '--target-dir', output / 'rust-target'])
        elif mode == 'java':
            classes = output / 'java-classes'
            classes.mkdir()
            compile_sources = [java_root / name for name in ('NativeFailure.java', 'NativePolicy.java', 'RequestRegistry.java', 'SessionState.java', 'DownloadAuthority.java', 'DownloadJob.java')]
            compile_sources += [native_tests / name for name in ('NativeCoreTest.java', 'DownloadAuthorityTest.java', 'DownloadJobTest.java')]
            run('javac-authority-job', [JDK / 'javac.exe', '-encoding', 'UTF-8', '-d', classes, *compile_sources])
            for test in ('NativeCoreTest', 'DownloadAuthorityTest', 'DownloadJobTest'):
                run('java-' + test, [JDK / 'java.exe', '-cp', classes, 'org.taiji.tireintelligence.mobile.' + test])
        else:
            snapshot = output / 'source-snapshot'
            for path in inputs:
                if path == Path(__file__).resolve():
                    continue
                destination = snapshot / path.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
            # cargo check uses dev cfg; no CLI beforeBuildCommand and no bundled frontend is executed.
            manifest = snapshot / 'apps/desktop/src-tauri/Cargo.toml'
            if mode == 'rust-host':
                run('cargo-host-lib', [CARGO, 'check', '--lib', '--locked', '--offline', '--manifest-path', manifest, '--target-dir', output / 'rust-target'], manifest.parent)
            else:
                for name in ('download_identity_admission_precedes_lifecycle_queue_and_cancellation_finishes_only_own_ticket',
                             'download_auth_end_revokes_even_when_response_reuses_identical_cookie_or_fails'):
                    run('cargo-bridge-' + name, [CARGO, 'test', '--lib', '--locked', '--offline', '--manifest-path', manifest,
                        '--target-dir', output / 'rust-target', 'bridge::tests::' + name, '--', '--exact'], manifest.parent)
        report['state'] = 'passed'
    except Exception as error:
        failure = error
        report['state'] = 'failed'
        report['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        try:
            report['sources_after'] = sources()
            report['sources_stable'] = report['sources_before'] == report['sources_after']
            if not report['sources_stable']:
                report['state'] = 'failed'
                failure = failure or RuntimeError('Source drift')
        except Exception as error:
            report['after_error'] = str(error)
            report['state'] = 'failed'
            failure = failure or error
        report['ended'] = datetime.now(timezone.utc).isoformat()
        report['retained_outputs'] = True
        save()
    return 1 if failure else 0


if __name__ == '__main__':
    raise SystemExit(main())
