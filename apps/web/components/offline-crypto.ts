// Device-history cryptography and strict JSON parsing. Never accesses networking.
export const MAX_OFFLINE_BYTES = 8 * 1024 * 1024;
export const MAX_OFFLINE_STORE_BYTES = 32 * 1024 * 1024;
export const MAX_OFFLINE_SLOTS = 16;

const messages: Record<string, string> = {
  OFFLINE_SYNC_INVALID: "持续更新参数无效，请重新预览。",
  OFFLINE_SYNC_UNSUPPORTED: "当前宿主无法可靠检测所选条件，未建立持续许可。",
  OFFLINE_SYNC_PREVIEW_USED: "本次预览已使用或内容不一致，请重新预览并授权。",
  OFFLINE_SYNC_PREVIEW_EXPIRED: "持续更新预览已到期，请重新预览并授权。",
  OFFLINE_SYNC_CONFLICT: "持续许可版本已变化，本次没有覆盖包，请重新读取。",
  OFFLINE_SYNC_BUSY: "已有持续更新正在处理，请稍后读取运行状态。",
  OFFLINE_SYNC_CONSENT_REQUIRED: "此包没有有效持续许可，请先预览并明确授权。",
  OFFLINE_SYNC_CORRUPT: "持续许可记录未通过完整性检查，同步已禁用；原包密文保留。",
  OFFLINE_SYNC_RESPONSE_INVALID: "服务器历史包响应与冻结范围或归属不符，本次保留旧包。",
  OFFLINE_SYNC_RESPONSE_UNKNOWN: "历史更新响应未能确认，许可已暂停；请重新预览授权，不会自动重试写入。",
  OFFLINE_SYNC_RESTARTED: "先前更新在页面或进程结束时中断，许可已暂停，请重新预览授权。",
  OFFLINE_SYNC_CONDITIONS: "所选条件尚未全部满足或状态未知，保留现有本机包。",
  OFFLINE_SYNC_CAPACITY: "持续更新超过已授权容量，本次保留旧包。",
  OFFLINE_SYNC_CANCELLED: "持续更新已取消，本次未发布新本机版本。",
  OFFLINE_SYNC_PAUSED: "持续更新已暂停，重新启用须重新预览授权。",
  OFFLINE_SYNC_REVOKED: "持续许可已撤销，设备历史包仍保留。",
  OFFLINE_SYNC_NOT_DUE: "尚未到达授权检查时间。",
  OFFLINE_RELEASE_VALIDATION_FAILED: "此设备包未通过当前宿主版本的完整校验，读取和更新已阻止，原密文仍保留。",
  OFFLINE_FALLBACK_INVALID: "本次设备回退请求无效，请重新查询。",
  OFFLINE_FALLBACK_UNSUPPORTED: "此查询或当前宿主不支持单次设备回退，仍可独立打开设备历史库。",
  OFFLINE_FALLBACK_EXPIRED: "这次设备授权已过期，请重新查询并作出新决定。",
  OFFLINE_FALLBACK_USED: "本次设备授权已使用或结束，请重新查询。",
  OFFLINE_FALLBACK_MISMATCH: "查询或授权内容不一致，本次未展示设备资料。",
  OFFLINE_FALLBACK_CAPACITY: "设备授权或完整响应超过容量限制，本次未返回部分资料。",
  OFFLINE_FALLBACK_NEVER: "此查询已设置不使用设备历史；旧的单次授权也不能继续使用。",
  OFFLINE_FALLBACK_AUTHORITY_UNKNOWN: "本次应用运行尚未成功观察来源权限，请恢复连接后重新读取来源元数据。",
  OFFLINE_FALLBACK_AUTHORITY_CHANGED: "来源权限、查询类型或归属已变化，请重新读取并预览许可。",
  OFFLINE_FALLBACK_POLICY_CHANGED: "设备历史许可或版本已变化，请重新读取并作出新决定。",
  OFFLINE_FALLBACK_SYNC_ADVANCE_SCOPE_UNAVAILABLE: "此包包含所选许可范围以外的来源；不能自动跟随更新。换包后需重新预览授权。",
  OFFLINE_OWNER_LOCKED: "资料归属已变化或属于旧归属，本次设备回退不可用。",
  OFFLINE_STALE_GENERATION: "所选设备包版本已变化，请重新查询并选择当前包。",
  OFFLINE_UNAVAILABLE: "此环境暂不支持设备离线库。",
  OFFLINE_STORAGE_UNAVAILABLE: "设备离线存储不可用；本次没有保存证据。",
  OFFLINE_KEY_UNAVAILABLE: "离线资料的加密密钥不可用，不能读取或写入。不会改用明文存储。",
  OFFLINE_CORRUPT: "离线包未通过完整性检查，请保留旧版或重新保存。",
  OFFLINE_INVALID_PACK: "离线包的结构或引用无效，未采纳该文件。",
  OFFLINE_TOO_LARGE: "离线包超过 8 MiB，请缩小范围后重新预览。",
  OFFLINE_HASH_MISMATCH: "离线包字节数或 SHA-256 与预览不符，未保存。",
  OFFLINE_SLOT_CONFLICT: "本机包版本已经变化，请重新读取后操作。",
  OFFLINE_GENERATION_CONFLICT: "本机包版本已经变化，请重新读取后操作。",
  OFFLINE_OWNER_CHANGED: "设备资料归属已变化，本次安装已取消。",
  OFFLINE_LOCKED: "这是旧归属的设备资料，请单独确认查看旧设备历史。",
  OFFLINE_PREVIOUS_OWNER_LOCKED: "这是旧归属的设备资料，请单独确认查看旧设备历史。",
  OFFLINE_NOT_FOUND: "此设备上没有找到该版本的离线包；站点数据清理或存储回收也可能移除它。",
  OFFLINE_QUOTA_EXCEEDED: "设备可用空间不足，本次没有保存新包；原有版本仍保留。",
  OFFLINE_INVALID_REQUEST: "离线操作参数无效，请重新选择包版本。",
  OFFLINE_INSTALL_BUSY: "另一个离线安装正在处理，请稍后重新读取状态。",
  OFFLINE_STORE_LIMIT: "已达到本设备的离线资料容量或包数量上限，请先删除不需要的包。",
  OFFLINE_STORE_FULL: "已达到本设备的离线资料容量或包数量上限，请先删除不需要的包。",
  OFFLINE_CONSENT_REQUIRED: "请先核对本次内容，并明确允许保存到设备。",
  OFFLINE_PREVIOUS_OWNER_CONSENT_REQUIRED: "请单独确认查看原归属的设备历史资料。",
  OFFLINE_DOWNLOAD_FAILED: "未能下载本次离线包，请恢复连接后重试；现有本机资料仍可查看。",
  OFFLINE_ENCRYPTION_FAILED: "设备加密未完成，本次没有保存新包；不会改用明文存储。",
  OFFLINE_GENERATION_EXHAUSTED: "此本机包的版本计数已耗尽，请另存为新的资料包。",
  OFFLINE_INDEX_UNAVAILABLE: "本机检索索引不可用，请重新读取或保存资料包。",
  OFFLINE_SEARCH_FAILED: "本机检索未完成，请重新读取资料包后重试。",
  API_UNAVAILABLE: "当前无法连接 API；已有设备历史仍可查看，新包需恢复连接后保存。",
  API_TIMEOUT: "本次下载等待超时；请先核对本机版本，再恢复连接重试。",
  API_REDIRECT_BLOCKED: "下载地址发生了不允许的重定向，本次未接受该文件。",
  REQUEST_CANCELLED: "本次请求已停止等待；请重新读取本机资料，核对是否已完成保存。",
  SESSION_CHANGED: "在线会话已变化，本次下载已停止；已有设备历史仍可单独查看。",
  SESSION_RESET_IN_PROGRESS: "在线会话正在重置，请完成后重新核对设备资料归属。",
};
const messageAliases: Record<string, string> = {
  OFFLINE_DOCUMENT_NOT_FOUND: "OFFLINE_NOT_FOUND", OFFLINE_SLOT_NOT_FOUND: "OFFLINE_NOT_FOUND",
  OFFLINE_INVALID_ARGUMENT: "OFFLINE_INVALID_REQUEST", OFFLINE_KEY_INVALID: "OFFLINE_KEY_UNAVAILABLE",
  OFFLINE_PACK_CORRUPT: "OFFLINE_CORRUPT", OFFLINE_PACK_INVALID: "OFFLINE_INVALID_PACK",
  OFFLINE_PACK_TOO_LARGE: "OFFLINE_TOO_LARGE", OFFLINE_RESPONSE_INVALID: "OFFLINE_INVALID_PACK",
  OFFLINE_STORE_FAILED: "OFFLINE_STORAGE_UNAVAILABLE", OFFLINE_UNSUPPORTED_PLATFORM: "OFFLINE_UNAVAILABLE",
};
const knownCode = (value: unknown): value is string => typeof value === "string" && (/^OFFLINE_[A-Z_]+$/.test(value) || Object.hasOwn(messages, value));

export class OfflineError extends Error {
  constructor(public readonly code: string) {
    super(messages[messageAliases[code] || code] || "设备离线操作未完成，请重新读取状态后重试。");
    this.name = "OfflineError";
  }
}

export function offlineError(cause: unknown): OfflineError {
  if (cause instanceof OfflineError) return cause;
  if (cause instanceof DOMException && cause.name === "QuotaExceededError") return new OfflineError("OFFLINE_QUOTA_EXCEEDED");
  if (knownCode(cause)) return new OfflineError(cause);
  if (cause && typeof cause === "object") {
    const value = cause as { code?: unknown; message?: unknown };
    if (knownCode(value.code)) return new OfflineError(value.code);
    if (knownCode(value.message)) return new OfflineError(value.message);
  }
  return new OfflineError("OFFLINE_STORAGE_UNAVAILABLE");
}

export async function offlineSha256(bytes: Uint8Array): Promise<string> {
  const result = await crypto.subtle.digest("SHA-256", bytes.slice().buffer);
  return Array.from(new Uint8Array(result), byte => byte.toString(16).padStart(2, "0")).join("");
}

export function parseOfflineJson(bytes: Uint8Array): unknown {
  if (!bytes.length || bytes.length > MAX_OFFLINE_BYTES) throw new OfflineError("OFFLINE_TOO_LARGE");
  if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) throw new OfflineError("OFFLINE_INVALID_PACK");
  let input: string;
  try { input = new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
  catch { throw new OfflineError("OFFLINE_INVALID_PACK"); }
  let position = 0;
  const fail = (): never => { throw new OfflineError("OFFLINE_INVALID_PACK"); };
  const whitespace = () => { while (/[\t\n\r ]/.test(input[position] || "x")) position++; };
  const string = (): string => {
    if (input[position++] !== '"') return fail();
    const start = position - 1;
    let escaped = false;
    while (position < input.length) {
      const next = input[position++];
      if (!escaped && next === '"') {
        let result: unknown;
        try { result = JSON.parse(input.slice(start, position)); } catch { return fail(); }
        if (typeof result !== "string" || /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(result)) return fail();
        return result;
      }
      escaped = !escaped && next === "\\";
    }
    return fail();
  };
  const value = (depth: number): unknown => {
    if (depth > 64) return fail();
    whitespace();
    const first = input[position];
    if (first === '"') return string();
    if (first === "{") {
      position++; whitespace();
      const object: Record<string, unknown> = {}, keys = new Set<string>();
      if (input[position] === "}") { position++; return object; }
      while (position < input.length) {
        const key = string();
        if (keys.has(key)) return fail();
        keys.add(key); whitespace();
        if (input[position++] !== ":") return fail();
        Object.defineProperty(object, key, { value: value(depth + 1), enumerable: true, writable: true, configurable: true });
        whitespace();
        const separator = input[position++];
        if (separator === "}") return object;
        if (separator !== ",") return fail();
        whitespace();
      }
      return fail();
    }
    if (first === "[") {
      position++; whitespace();
      const array: unknown[] = [];
      if (input[position] === "]") { position++; return array; }
      while (position < input.length) {
        array.push(value(depth + 1)); whitespace();
        const separator = input[position++];
        if (separator === "]") return array;
        if (separator !== ",") return fail();
      }
      return fail();
    }
    for (const [token, result] of [["true", true], ["false", false], ["null", null]] as const) {
      if (input.startsWith(token, position)) { position += token.length; return result; }
    }
    const number = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(input.slice(position));
    if (!number) return fail();
    position += number[0].length;
    const result = Number(number[0]);
    if (!Number.isFinite(result) || (Number.isInteger(result) && !Number.isSafeInteger(result))) return fail();
    return result;
  };
  const result = value(0); whitespace();
  if (position !== input.length) return fail();
  return result;
}

export interface OfflineCiphertext { iv: Uint8Array; ciphertext: ArrayBuffer }
export async function newOfflineKey(): Promise<CryptoKey> {
  if (!globalThis.crypto?.subtle) throw new OfflineError("OFFLINE_KEY_UNAVAILABLE");
  return crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

export async function sealOfflineBytes(key: CryptoKey, bytes: Uint8Array, binding: string): Promise<OfflineCiphertext> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: new TextEncoder().encode(binding) }, key, bytes.slice().buffer);
  return { iv, ciphertext };
}

export async function openOfflineBytes(key: CryptoKey, value: OfflineCiphertext, binding: string): Promise<Uint8Array> {
  try {
    if (!(value.iv instanceof Uint8Array) || value.iv.byteLength !== 12 || !(value.ciphertext instanceof ArrayBuffer)) throw new Error();
    return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: value.iv.slice().buffer,
      additionalData: new TextEncoder().encode(binding) }, key, value.ciphertext));
  } catch { throw new OfflineError("OFFLINE_CORRUPT"); }
}
