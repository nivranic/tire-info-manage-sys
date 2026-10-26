"""R96 offline javac of every current Android app production Java source.

prepare only snapshots bytes and writes an exact command; compile requires the
SHA-256 of that immutable plan. No Gradle, Node, APK, resource generation,
product imports, device, services, dependency downloads, or handwritten stubs.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
JAVA_ROOT = ROOT / 'apps/mobile/android/app/src/main/java'
BUILD_CONFIG = ROOT / 'apps/mobile/android/app/build/generated/source/buildConfig/debug/org/taiji/tireintelligence/mobile/BuildConfig.java'
CACHE = ROOT / '.artifacts/mobile/gradle/caches/modules-2/files-2.1'
JAVAC = Path('D:/JAVA_21/bin/javac.exe')
ANDROID = Path('E:/Android_Studio_SDK/platforms/android-36/android.jar')
CAPACITOR = ROOT / 'node_modules/@capacitor/android/capacitor/build/intermediates/compile_library_classes_jar/debug/bundleLibCompileToJarDebug/classes.jar'
# Exact cached artifact coordinates. This is a bounded javac classpath, not a
# claim that Gradle has resolved or checked the current transitive graph.
DEPENDENCIES = (
    ('androidx.activity', 'activity', '1.11.0', 'aar'),
    ('androidx.appcompat', 'appcompat', '1.7.1', 'aar'),
    ('androidx.appcompat', 'appcompat-resources', '1.7.1', 'aar'),
    ('androidx.annotation', 'annotation-jvm', '1.9.1', 'jar'),
    ('androidx.annotation', 'annotation-experimental', '1.4.1', 'aar'),
    ('androidx.arch.core', 'core-common', '2.2.0', 'jar'),
    ('androidx.arch.core', 'core-runtime', '2.2.0', 'aar'),
    ('androidx.collection', 'collection-jvm', '1.4.2', 'jar'),
    ('androidx.concurrent', 'concurrent-futures', '1.1.0', 'jar'),
    ('androidx.coordinatorlayout', 'coordinatorlayout', '1.3.0', 'aar'),
    ('androidx.core', 'core', '1.17.0', 'aar'),
    ('androidx.core', 'core-splashscreen', '1.2.0', 'aar'),
    ('androidx.drawerlayout', 'drawerlayout', '1.0.0', 'aar'),
    ('androidx.fragment', 'fragment', '1.8.9', 'aar'),
    ('androidx.lifecycle', 'lifecycle-common', '2.6.2', 'jar'),
    ('androidx.lifecycle', 'lifecycle-runtime', '2.6.2', 'aar'),
    ('androidx.lifecycle', 'lifecycle-viewmodel', '2.6.2', 'aar'),
    ('androidx.lifecycle', 'lifecycle-viewmodel-savedstate', '2.6.2', 'aar'),
    ('androidx.lifecycle', 'lifecycle-livedata-core', '2.6.2', 'aar'),
    ('androidx.savedstate', 'savedstate', '1.2.1', 'aar'),
    ('androidx.sqlite', 'sqlite-android', '2.7.1', 'aar'),
    ('androidx.sqlite', 'sqlite-bundled-android', '2.7.1', 'aar'),
    ('androidx.webkit', 'webkit', '1.14.0', 'aar'),
    ('androidx.work', 'work-runtime', '2.10.1', 'aar'),
    ('com.google.guava', 'listenablefuture', '1.0', 'jar'),
    ('com.squareup.okhttp3', 'okhttp', '4.12.0', 'jar'),
    ('com.squareup.okio', 'okio-jvm', '3.6.0', 'jar'),
    ('org.jetbrains.kotlin', 'kotlin-stdlib', '2.2.0', 'jar'),
)
CONFIGS = (
    'apps/mobile/android/app/build.gradle',
    'apps/mobile/android/app/capacitor.build.gradle',
    'apps/mobile/android/app/src/main/AndroidManifest.xml',
    'apps/mobile/android/build.gradle',
    'apps/mobile/android/variables.gradle',
    'apps/mobile/android/settings.gradle',
    'apps/mobile/android/capacitor.settings.gradle',
    'apps/mobile/android/gradle.properties',
    'node_modules/@capacitor/android/capacitor/build.gradle',
    'node_modules/@capacitor/android/package.json',
    '.artifacts/mobile/gradle/caches/modules-2/files-2.1/androidx.appcompat/appcompat/1.7.1/b03a9adbcce3c54f15e0d0be60c7afe4d0060870/appcompat-1.7.1.pom',
)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding(path):
    return {'path': path.as_posix(), 'bytes': path.stat().st_size, 'sha256': digest(path)}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def private_root(value, must_exist):
    path = Path(value).resolve()
    if path.parent != (ROOT / '.artifacts').resolve() or not re.fullmatch(r'r96-android-[a-f0-9]{32}', path.name):
        raise ValueError('Exact .artifacts/r96-android-<32 lowercase hex> private root required')
    if path.exists() != must_exist:
        raise ValueError('Private root must ' + ('already exist' if must_exist else 'be fresh'))
    return path


def sources():
    paths = sorted(JAVA_ROOT.rglob('*.java'))
    if not paths or not all((JAVA_ROOT / ('org/taiji/tireintelligence/mobile/' + name)).is_file() for name in
                            ('DownloadAuthority.java', 'DownloadJob.java', 'OfflineRuntime.java', 'NativeHttpBridge.java', 'TireNativePlugin.java', 'MainActivity.java')):
        raise ValueError('Full current production Java tree required')
    # No R is fabricated. If application resources become a Java dependency,
    # this wrapper must be reviewed with a real generated R input instead.
    for path in paths:
        if re.search(r'\bR\.', path.read_text(encoding='utf-8')):
            raise ValueError('Application R dependency requires a separately reviewed real generated input')
    return paths


def input_paths():
    paths = sources() + [BUILD_CONFIG, SCRIPT, ANDROID, CAPACITOR]
    paths += [ROOT / relative for relative in CONFIGS]
    paths += [Path('D:/JAVA_21') / relative for relative in
              ('release', 'bin/javac.exe', 'bin/java.exe', 'bin/server/jvm.dll', 'bin/jli.dll', 'lib/modules')]
    dependencies = []
    for group, artifact, version, extension in DEPENDENCIES:
        candidates = sorted((CACHE / group / artifact / version).glob('*/*.' + extension))
        candidates = [p for p in candidates if not p.name.endswith(('-sources.jar', '-javadoc.jar'))]
        if len(candidates) != 1:
            raise ValueError('Exactly one cached binary required: ' + ':'.join((group, artifact, version)))
        dependencies.append((group + ':' + artifact + ':' + version, candidates[0]))
    paths += [p for _, p in dependencies]
    return sorted(set(paths)), dependencies


def inventory(paths):
    return [binding(path) for path in paths]


def quote_arg(value):
    text = str(value)
    if '\n' in text or '\r' in text or '"' in text:
        raise ValueError('Unsafe javac argument')
    return '"' + text.replace('\\', '/') + '"'


def javac_argv(output):
    # Launcher -J options are prohibited inside javac @argument files.
    return [JAVAC.as_posix(), '-J-Djava.io.tmpdir=' + (output / 'tmp').as_posix(),
            '-J-Duser.home=' + (output / 'home').as_posix(), '-J-Duser.language=en', '-J-Duser.country=US',
            '@' + (output / 'javac.args').as_posix()]


def prepare(output):
    output.mkdir()
    report = {'schema': 'r96-android-full-java-compile@1', 'state': 'preparing', 'started': now(),
              'sources_before': None, 'sources_after': None, 'sources_stable': None,
              'scope': 'Compile every current app/src/main/java production Java source, including Plugin/HttpBridge/Runtime/MainActivity, against real cached Android/Capacitor/AndroidX binaries. No generated resource, Gradle resolution, D8/desugaring, packaging, runtime, SAF or device acceptance.',
              'cached_transitives_notice': 'The listed cached transitive versions are javac support inputs, not a current Gradle resolved dependency graph.',
              'build_config_notice': 'Existing generated debug BuildConfig.java is copied verbatim, is not regenerated and may hold an older OFFLINE_HOST_BUILD; its constants do not identify this source snapshot.',
              'original_inputs_modified': False, 'gradle_executed': False, 'device_executed': False,
              'dependencies': [], 'copied_inputs': [], 'phase': None, 'error': None}
    verification = output / 'verification.json'
    write_json(verification, report)
    try:
        paths, dependencies = input_paths()
        before = inventory(paths)
        report['sources_before'] = before
        write_json(verification, report)
        for name in ('snapshot', 'deps', 'classes', 'tmp', 'home', 'empty-sourcepath'):
            (output / name).mkdir()
        compile_sources = []
        for path in sources() + [BUILD_CONFIG]:
            relative = path.relative_to(ROOT)
            destination = output / 'snapshot' / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            if digest(destination) != digest(path):
                raise ValueError('Source snapshot mismatch')
            compile_sources.append(destination)
            report['copied_inputs'].append(binding(destination))
        classpath = []
        for coordinate, path in [('android-sdk-api36', ANDROID), ('capacitor-android-debug-cached', CAPACITOR), *dependencies]:
            record = {'coordinate': coordinate, 'original': binding(path), 'classpath': []}
            if path.suffix == '.aar':
                with zipfile.ZipFile(path) as archive:
                    members = sorted(name for name in archive.namelist() if name == 'classes.jar' or re.fullmatch(r'libs/[^/]+\.jar', name))
                    if 'classes.jar' not in members:
                        raise ValueError('AAR has no real classes.jar: ' + coordinate)
                    for member in members:
                        destination = output / 'deps' / (str(len(classpath)).zfill(3) + '-' + coordinate.replace(':', '-') + '-' + Path(member).name)
                        destination.write_bytes(archive.read(member))
                        record['classpath'].append({'aar_member': member, **binding(destination)})
                        classpath.append(destination)
            else:
                destination = output / 'deps' / (str(len(classpath)).zfill(3) + '-' + coordinate.replace(':', '-') + '.jar')
                shutil.copyfile(path, destination)
                record['classpath'].append(binding(destination))
                classpath.append(destination)
            report['dependencies'].append(record)
        arguments = ['-encoding', 'UTF-8', '-source', '21', '-target', '21', '-proc:none', '-implicit:none',
                     '-sourcepath', (output / 'empty-sourcepath').as_posix(), '-classpath', os.pathsep.join(p.as_posix() for p in classpath),
                     '-d', (output / 'classes').as_posix(), *[p.as_posix() for p in compile_sources]]
        argfile = output / 'javac.args'
        argfile.write_text('\n'.join(quote_arg(arg) for arg in arguments) + '\n', encoding='utf-8')
        plan = {'schema': 'r96-android-javac-plan@1', 'cwd': output.as_posix(),
                'argv': javac_argv(output), 'expanded_arguments': arguments,
                'inputs': before, 'production_java_count': len(compile_sources) - 1,
                'snapshot_inputs': report['copied_inputs'], 'classpath_inputs': [binding(p) for p in classpath],
                'argfile': binding(argfile), 'timeout_seconds': 600}
        write_json(output / 'compile-plan.json', plan)
        report['sources_after'] = inventory(paths)
        report['sources_stable'] = report['sources_before'] == report['sources_after']
        if not report['sources_stable']:
            raise ValueError('Source or dependency drift while preparing')
        report['state'] = 'prepared_not_executed'
        report['compile_plan'] = binding(output / 'compile-plan.json')
    except Exception as error:
        report['state'] = 'prepare_failed'
        report['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        report['ended'] = now()
        write_json(verification, report)
    print(json.dumps({'output': output.as_posix(), 'script': binding(SCRIPT), 'plan': report['compile_plan'],
                      'production_java_count': plan['production_java_count'], 'argv': plan['argv'], 'state': report['state']}), flush=True)


def compile_plan(output, expected):
    if not re.fullmatch(r'[a-f0-9]{64}', expected):
        raise ValueError('Exact reviewed plan SHA-256 required')
    plan_path = output / 'compile-plan.json'
    if digest(plan_path) != expected:
        raise ValueError('Reviewed compile plan changed')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    report_path = output / 'verification.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if report['state'] != 'prepared_not_executed':
        raise ValueError('Prepared output is single-use; preserve prior results')
    report['state'] = 'running'
    report['sources_after'] = None
    report['sources_stable'] = None
    report['run_started'] = now()
    write_json(report_path, report)
    failure = None
    paths = [Path(item['path']) for item in plan['inputs']]
    expected_argv = javac_argv(output)
    try:
        if plan['argv'] != expected_argv or plan['cwd'] != output.as_posix() or plan['timeout_seconds'] != 600:
            raise ValueError('Command is outside exact javac allowlist')
        if any((output / 'classes').iterdir()):
            raise ValueError('Prepared classes directory must be empty before single-use compile')
        if inventory(paths) != plan['inputs'] or sorted(p.as_posix() for p in sources()) != sorted(item['path'] for item in plan['inputs'] if item['path'].startswith(JAVA_ROOT.as_posix() + '/')):
            raise ValueError('Source or dependency drift before javac')
        for record in [*plan['snapshot_inputs'], *plan['classpath_inputs'], plan['argfile']]:
            path = Path(record['path']).resolve()
            if not path.is_relative_to(output) or binding(path) != record:
                raise ValueError('Prepared private input changed or escaped')
        # Allowlist only OS/JDK discovery variables; no inherited proxy,
        # provider, database, Java agent, classpath, or JVM-option variables.
        env = {key: value for key, value in os.environ.items() if key.upper() in
               {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'SYSTEMDRIVE', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS'}}
        env.update(JAVA_HOME='D:/JAVA_21', PATH='D:/JAVA_21/bin', TEMP=str(output / 'tmp'), TMP=str(output / 'tmp'),
                   TMPDIR=str(output / 'tmp'), USERPROFILE=str(output / 'home'))
        def audit(event, args):
            if event.startswith(('socket.', 'os.system', 'os.startfile', 'os.spawn', 'os.exec')):
                raise RuntimeError('Forbidden process/network operation: ' + event)
            if event == 'subprocess.Popen':
                executable, argv, cwd, child_env = args
                if str(executable) != expected_argv[0] or argv != subprocess.list2cmdline(expected_argv) or str(cwd) != output.as_posix() or child_env != env:
                    raise RuntimeError('Child is outside exact javac command')
        sys.addaudithook(audit)
        phase = {'argv': expected_argv, 'cwd': output.as_posix(), 'started': now(), 'exit_code': None,
                 'executable_sha256': digest(JAVAC), 'stdout': (output / 'javac.stdout.log').as_posix(),
                 'stderr': (output / 'javac.stderr.log').as_posix()}
        report['phase'] = phase
        write_json(report_path, report)
        with (output / 'javac.stdout.log').open('xb') as stdout, (output / 'javac.stderr.log').open('xb') as stderr:
            try:
                result = subprocess.run(expected_argv, executable=JAVAC.as_posix(), cwd=output.as_posix(), env=env, stdin=subprocess.DEVNULL,
                                        stdout=stdout, stderr=stderr, timeout=600, shell=False)
                phase['exit_code'] = result.returncode
            finally:
                phase['ended'] = now()
                write_json(report_path, report)
        if phase['exit_code'] != 0:
            raise RuntimeError('javac failed; original stdout/stderr retained')
        classes = sorted((output / 'classes').rglob('*.class'))
        required = ('DownloadAuthority', 'DownloadJob', 'NativeHttpBridge', 'OfflineRuntime', 'TireNativePlugin', 'MainActivity')
        for name in required:
            if not (output / 'classes/org/taiji/tireintelligence/mobile' / (name + '.class')).is_file():
                raise RuntimeError('Expected full host class missing: ' + name)
        report['compiled_classes'] = inventory(classes)
        report['compiled_class_count'] = len(classes)
        report['production_java_count'] = plan['production_java_count']
        report['state'] = 'passed'
    except Exception as error:
        failure = error
        report['state'] = 'failed'
        report['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        try:
            report['sources_after'] = inventory(paths)
            report['sources_stable'] = report['sources_before'] == report['sources_after']
            if not report['sources_stable']:
                report['state'] = 'failed'
                failure = failure or RuntimeError('Source or dependency drift after javac')
        except Exception as error:
            report['state'] = 'failed'
            report['after_error'] = type(error).__name__ + ': ' + str(error)
            failure = failure or error
        report['run_ended'] = now()
        report['retained_outputs'] = True
        write_json(report_path, report)
    print(json.dumps({'output': output.as_posix(), 'state': report['state'], 'phase': report['phase'],
                      'sources_stable': report['sources_stable'], 'error': report['error']}), flush=True)
    return 1 if failure else 0


def main():
    if len(sys.argv) == 3 and sys.argv[1] == 'prepare':
        prepare(private_root(sys.argv[2], False))
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == 'compile':
        return compile_plan(private_root(sys.argv[2], True), sys.argv[3])
    raise SystemExit('Usage: isolated-python script prepare fresh-root | compile prepared-root reviewed-plan-sha256')


if __name__ == '__main__':
    raise SystemExit(main())
