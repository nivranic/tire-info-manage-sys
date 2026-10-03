// Local native WebView inspection helper. Debugging must be enabled explicitly on a QA process.
import { writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

export async function connect(port = 9223, platform = 'desktop') {
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid CDP port');
  if (!['desktop', 'mobile'].includes(platform)) throw new Error('Invalid native platform');
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = pages.find(value => {
    if (value.type !== 'page') return false;
    try {
      const url = new URL(value.url);
      if (platform === 'mobile') return url.protocol === 'https:' && url.hostname === 'localhost' && !url.username && !url.password && !url.port;
      return !url.username && !url.password && !url.port && (
        (url.protocol === 'http:' && url.hostname === 'tauri.localhost') ||
        (url.protocol === 'tauri:' && url.hostname === 'localhost'));
    } catch { return false; }
  });
  if (!page) throw new Error('No expected packaged native page found; dev-server/browser pages are not acceptance evidence');
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  let sequence = 0;
  const pending = new Map();
  const events = [];
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) {
      const item = pending.get(message.id);
      if (!item) return;
      pending.delete(message.id);
      clearTimeout(item.timer);
      if (message.error) item.reject(new Error(JSON.stringify(message.error)));
      else item.resolve(message.result);
    } else if (['Runtime.exceptionThrown', 'Log.entryAdded'].includes(message.method)) {
      events.push(message);
    }
  });
  function call(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 45000);
      pending.set(id, { resolve, reject, timer });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }
  await call('Runtime.enable');
  await call('Log.enable');
  return {
    url: page.url, call, events,
    async evaluate(expression) {
      const value = await call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (value.exceptionDetails) throw new Error(JSON.stringify(value.exceptionDetails));
      return value.result.value;
    },
    async screenshot(path) {
      const { data } = await call('Page.captureScreenshot', { format: 'png' });
      await writeFile(path, Buffer.from(data, 'base64'));
    },
    close() { socket.close(); },
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const client = await connect(Number(process.argv[2] || 9223));
  try {
    const result = await client.evaluate(process.argv[3] || '({title:document.title,url:location.href,text:document.body.innerText})');
    console.log(JSON.stringify(result, null, 2));
  } finally { client.close(); }
}
