import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = path.resolve(here, '../android/app/src/main/java/org/taiji/tireintelligence/mobile');
const temporaryRoot = path.resolve(tmpdir());
const output = path.resolve(await mkdtemp(path.join(temporaryRoot, 'tire-mobile-native-')));
const executable = name => process.env.JAVA_HOME ? path.join(process.env.JAVA_HOME, 'bin', name + (process.platform === 'win32' ? '.exe' : '')) : name;
function run(name, args) {
  const result = spawnSync(executable(name), args, { encoding: 'utf8', stdio: 'pipe' });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${name} exited ${result.status}`);
}
try {
  run('javac', ['-encoding', 'UTF-8', '-d', output, ...['NativeFailure.java', 'NativePolicy.java', 'RequestRegistry.java', 'SessionState.java', 'DownloadJob.java'].map(name => path.join(source, name)), path.join(here, 'NativeCoreTest.java'), path.join(here, 'DownloadJobTest.java')]);
  run('java', ['-cp', output, 'org.taiji.tireintelligence.mobile.NativeCoreTest']);
  run('java', ['-cp', output, 'org.taiji.tireintelligence.mobile.DownloadJobTest']);
} finally {
  const relative = path.relative(temporaryRoot, output);
  if (path.dirname(output) !== temporaryRoot || !path.basename(output).startsWith('tire-mobile-native-')
      || !relative || path.isAbsolute(relative) || relative.startsWith('..' + path.sep) || relative === '..') {
    throw new Error('Refusing to remove an unsafe native-test temporary directory');
  }
  await rm(output, { recursive: true, force: true });
}
