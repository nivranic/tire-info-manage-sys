# Webhook 使用与接收约定

Webhook 将未来新建的站内通知引用发送给本机操作者预设的 HTTPS 接收端。默认没有接收目标，订阅默认暂停。它不发送轮胎数值、来源原文、私人规则名称、兴趣条件、账户标识或证据原件。完整来源事实导出仍受原有用途许可约束。

## 配置接收目标

将 [示例目录](webhook-targets.example.json) 复制到本机管理路径，修改目标后通过 `TI_WEBHOOK_TARGETS_FILE` 指向该 JSON 文件。目录至多 16 个目标、256 KiB；目标 URL 只允许公网域名 HTTPS、443 端口，不带用户名、密码、查询参数或片段。不能使用 IP 字面量、数字地址、内网地址、跳转或环境代理。

`signing_key_env` 是环境变量名称，格式为 `TI_WEBHOOK_SIGNING_[A-Z0-9_]+`。仅在服务和 Worker 的运行环境中设置一个随机 32 字节密钥的 64 位十六进制值；接收端通过自己的保密配置取得同一密钥。不要把值填入目录、聊天、Git、命令历史或前端。目录和密钥加载后，修改配置需重启相应进程。

目标列表只公开目标 ID、标题、接收域名、就绪状态和策略指纹。无效目录整体关闭 Webhook 派送，正常查询仍可使用。缺密钥时可创建暂停草稿，不能启用。URL、目录或密钥变化会改变策略指纹；须重新明确同意，新修订不能使旧队列复活。

## 创建与操作订阅

登录后在监控面板的 Webhook 区域选择目标和通知类型。轮胎监控规则是本机共享数据，选择这一类型表示接收共享轮胎提醒引用；召回类型仅包含已经形成 `RecallEvent` 的规则通知，不包含召回发现候选；兴趣通知限于本人账户。

私人通知在创建时冻结其当时的未过期登录账户。匿名或过期会话不外发，后来更换会话账户也不能改投给新账户。创建或启用订阅不会补发已有通知。

启用需要明确勾选外发同意。编辑、暂停、恢复或归档都会追加订阅修订，并使旧修订的待发队列失效。恢复归档订阅后仍保持暂停。换接收目标须另建订阅。每账户最多 16 个未归档订阅，每订阅最多 1000 个未终态投递；超出时仍保留站内通知，页面用累计省略次数及最后省略时间表示未入队数量，不能视为已送达。

所有写操作带 UUID `Idempotency-Key`。首次成功返回 `webhook-operation@1` 冻结动作回执，`response` 是该动作完成当时的快照，`current` 固定为 `false`。同键重放与只读恢复返回 `replayed=true`。请求超时后保留 UUID，通过 `GET /v1/webhook-operations?mode=history&key=<UUID>` 查回该动作；404 表示当前未找到动作记录，不能靠订阅名称猜测成功，也不要自动重复 POST。查看当前状态使用订阅或投递的专用 GET。

## 派送与故障

Worker 在已启用订阅产生新通知时处理事务内队列。单独处理 Webhook 可使用 `python apps/worker/monitor.py --webhooks-once`；常规监控 cycle 也会处理队列。配置为空或没有已启用订阅时没有外发。不要通过 GET、页面加载或“测试连接”隐式发送。

单次请求总超时 8 秒，不跟随跳转，响应体上限 64 KiB且不保存。只以 2xx 确认对端接收；408、429、5xx 和网络超时可有限重试，其他 4xx、3xx、无效目标及超限响应会明确失败。自动尝试最多 5 次，退避为 60、300、1800、7200 秒；429/503 的整数 `Retry-After` 限定在 1–3600 秒。队列有效期 7 天，跨进程并发为 1，每目标 claim 间隔至少 1 秒。

人工重试每次增加 5 次预算，总上限 20，保留原 delivery ID、正文和连续 attempt 编号。仅仍有效的原订阅修订、未过期且完整的失败投递可以重试。取消、成功、损坏、策略变化或过期修订不能重新发送。取消或暂停只能停止后续派送，无法追回已经开始的 HTTP 请求；超时、进程崩溃或租约过期也无法证明对端未收到。取消后到达的响应只能记录尝试事实，不能把取消状态改回已送达。

## 接收方签名核验

请求正文是封闭的 `tire-webhook-event@1` JSON：`delivery_id`、`channel`、`notification_id`、`event_id`、`domain`、`occurred_at`、`data_scope=notification_reference_only` 以及固定边界文字。`tire_monitor` 的 event ID 是 `AlertEvent.id`，时间来自关联 `ChangeEvent.observed_at`；其他两类分别使用 `RecallEvent`、`InterestEvent`，只有兴趣类型有非空 domain。

签名头包括：

- `X-Tire-Webhook-Id`：稳定 delivery ID。
- `X-Tire-Webhook-Attempt`：从 1 开始的连续尝试编号。
- `X-Tire-Webhook-Timestamp`：UTC Unix 整数秒的 ASCII 十进制文本。
- `X-Tire-Webhook-Signature`：`v1=` 加小写十六进制摘要。

签名输入为 `timestamp + '.' + delivery_id + '.' + attempt_number + '.' + raw_body`。前三段为 ASCII，`raw_body` 为收到的 UTF-8 原字节；不能先解析再重新序列化。发送端 JSON 使用排序字段、无额外空格、无 BOM、无尾换行。以下为核验核心示例，`raw_body` 和头应由接收服务框架提供，密钥从接收端自己的保密配置读取：

```python
import hashlib
import hmac
import json
import re
import time

def verify(raw_body, headers, signing_key_hex, now=None):
    stamp = headers['X-Tire-Webhook-Timestamp']
    delivery_id = headers['X-Tire-Webhook-Id']
    attempt = headers['X-Tire-Webhook-Attempt']
    signature = headers['X-Tire-Webhook-Signature']
    if not re.fullmatch(r'[0-9]{1,12}', stamp):
        return False
    if not re.fullmatch(r'[1-9]|1[0-9]|20', attempt):
        return False
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', delivery_id):
        return False
    if not re.fullmatch(r'[a-fA-F0-9]{64}', signing_key_hex):
        return False
    if abs((time.time() if now is None else now) - int(stamp)) > 300:
        return False
    prefix = f'{stamp}.{delivery_id}.{attempt}.'.encode('ascii')
    expected = 'v1=' + hmac.new(bytes.fromhex(signing_key_hex),
        prefix + raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False
    event = json.loads(raw_body.decode('utf-8'))
    return (event.get('schema') == 'tire-webhook-event@1'
        and event.get('delivery_id') == delivery_id
        and event.get('data_scope') == 'notification_reference_only')
```

接收服务还应限制请求体大小，安全处理缺头、解码及 JSON 错误，并在同一持久事务中按 `delivery_id` 去重及入站记账。先持久接收，再返回 2xx；业务处理可从本地入站队列继续。不能仅按 attempt 编号去重，也不能依赖内存集合跨重启防重放。该接口为至少一次派送；任何重试机制都不能承诺恰好一次。

## 验收边界

本轮工程验收使用私有 SQLite、合成通知与受控发送边界。真实公网接收端、生产部署、长周期队列延迟、PostgreSQL 和原生设备运行须分别取得证据。现有本机会话聚合不是全站服务器账户隔离保证。本说明不把模块测试视为完整 V1 验收。
