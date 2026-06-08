# Hermes Agent — HTTP API 对接文档

本服务基于 [Hermes Agent](https://github.com/NousResearch/hermes-agent)(Nous Research)的内置 API Server,对外暴露 **OpenAI 兼容**的 HTTP 接口。任何能调用 OpenAI API 的客户端、SDK 或框架,都可以直接对接本服务。

> **一句话理解**:你发一段文字指令,Hermes 这个 AI 智能体会自主思考、按需调用工具(执行命令、读写文件、联网搜索等),最后把结果通过 HTTP 返回给你。它不是单纯的"大模型代理",而是一个带全套工具和记忆的 Agent。

---

## 1. 基本信息

| 项目 | 值 |
|------|-----|
| 协议 | HTTP / HTTPS |
| 接口风格 | OpenAI Chat Completions / Responses 兼容 |
| 默认 Base URL | `http://<服务器地址>:8088/v1` |
| 鉴权方式 | Bearer Token(HTTP Header) |
| 数据格式 | JSON(UTF-8) |
| 字符编码说明 | 中文在 JSON 中以 `\uXXXX` 转义返回,任何标准 JSON 库解析后即为正常中文 |

> 把上面的 `<服务器地址>` 换成实际的主机名或 IP。本机调用时使用 `localhost`。

---

## 2. 鉴权(必读)

所有接口(健康检查除外)都需要在请求头中携带 Bearer Token:

```
Authorization: Bearer YOUR_API_SERVER_KEY
```

- 令牌由服务提供方分配,请向管理员索取。
- **令牌请妥善保管**:持有该令牌即可让 Agent 在服务端执行任意命令(终端、文件读写等),权限很高,等同于服务器操作权限,切勿泄露或硬编码进公开仓库。
- 令牌错误或缺失会返回 **401 Unauthorized**。

---

## 3. 快速开始

### 3.1 健康检查(无需鉴权)

确认服务是否在线:

```bash
curl http://<服务器地址>:8088/health
```

返回:

```json
{"status": "ok", "platform": "hermes-agent"}
```

### 3.2 发送第一条指令

```bash
curl -X POST http://<服务器地址>:8088/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_SERVER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hermes-agent",
    "messages": [
      {"role": "user", "content": "列出当前目录的文件"}
    ]
  }'
```

> **提示**:Agent 收到请求后会思考并调用工具,响应可能需要数秒到数十秒,属正常现象,请勿过早超时(建议客户端超时设置 ≥ 120 秒)。

---

## 4. 核心接口:POST /v1/chat/completions

最常用的接口,标准 OpenAI Chat Completions 格式。**无状态**——服务端不记忆上一轮对话,多轮对话需由调用方在 `messages` 数组中带上完整历史。

### 4.1 请求字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | 是 | **装饰性字段**。填什么都可以(建议填 `hermes-agent`)。实际使用的大模型由服务端配置决定,客户端无法通过此字段切换模型。 |
| `messages` | array | 是 | 对话消息数组,见下方角色说明。 |
| `stream` | boolean | 否 | 是否流式返回。默认 `false`。设为 `true` 时返回 SSE 流(见第 6 节)。 |

**`messages` 中的 `role`(角色):**

| role | 含义 |
|------|------|
| `system` | 系统指令,用于追加额外的行为约束(见 4.4 节)。 |
| `user` | 用户/调用方发出的指令或问题。 |
| `assistant` | Agent 之前轮次的回复(多轮对话时回填)。 |

### 4.2 请求示例

```json
{
  "model": "hermes-agent",
  "messages": [
    {"role": "system", "content": "你是一个严谨的运维助手,回答尽量简洁。"},
    {"role": "user", "content": "检查一下磁盘使用情况"}
  ],
  "stream": false
}
```

### 4.3 响应字段

```json
{
  "id": "chatcmpl-ea7b1a0f59f24002bdea00d667cff",
  "object": "chat.completion",
  "created": 1780710687,
  "model": "hermes-agent",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "你好！有什么我可以帮你的？"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 13031,
    "completion_tokens": 85,
    "total_tokens": 13116
  }
}
```

| 字段 | 说明 |
|------|------|
| `id` | 本次响应唯一标识(`chatcmpl-` 前缀),用于排查与日志关联。 |
| `object` | 固定为 `chat.completion`(非流式结果)。 |
| `created` | 响应生成时间(Unix 秒级时间戳)。 |
| `model` | 回显的模型名(即请求里发的装饰性值)。 |
| `choices[0].message.content` | **核心字段:Agent 的最终文本回复。调用方主要取这个值。** |
| `choices[0].finish_reason` | 结束原因。`stop`=正常结束;`length`=被最大 token 限制截断;`tool_calls`=因工具调用而停。 |
| `usage` | Token 用量。`prompt_tokens`=输入,`completion_tokens`=输出,`total_tokens`=合计。 |

### 4.4 关于 `prompt_tokens` 偏大的说明

即使只发一句"你好",`prompt_tokens` 也可能上万。这是正常的:Hermes 是 Agent,每次请求服务端会自动拼入它的系统提示词、工具定义、记忆等大量上下文。**这部分对调用方透明,无需处理**,但若需核算调用成本,应以此为依据。

### 4.5 关于 `system` 消息的行为

当调用方传入 `system` 消息时,它会**叠加**在 Hermes 自身的核心系统提示词之上,而**不是替换**。也就是说 Agent 仍保留全部工具、记忆和技能能力,你的 `system` 只是追加的额外指令。可借此实现"按调用方定制行为而不丢失能力"。

---

## 5. 多轮对话(两种方式)

### 5.1 方式一:无状态,客户端自带历史(chat/completions)

每次请求把完整对话历史放进 `messages`:

```json
{
  "model": "hermes-agent",
  "messages": [
    {"role": "user", "content": "我叫张三"},
    {"role": "assistant", "content": "你好张三！"},
    {"role": "user", "content": "我叫什么名字？"}
  ]
}
```

适合:调用方自己管理会话历史的场景。

### 5.2 方式二:服务端保存状态(/v1/responses)

使用 `/v1/responses` 接口,可由**服务端保存对话状态**,客户端不必每次回传完整历史。详见第 7 节。

---

## 6. 流式返回与工具进度(stream: true)

若希望**实时看到 Agent 的回复和它正在调用哪些工具**,在请求中设置 `"stream": true`。接口将返回 Server-Sent Events(SSE)流。

```bash
curl -N -X POST http://<服务器地址>:8088/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_SERVER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hermes-agent",
    "stream": true,
    "messages": [{"role": "user", "content": "统计当前目录有多少个文件"}]
  }'
```

流中包含两类事件:

- 标准的 `chat.completion.chunk` 事件:逐 token 推送回复文本。
- 自定义的 `hermes.tool.progress` 事件:在 Agent **开始调用某个工具**时推送,用于向用户展示"正在执行 xxx",且不会污染最终持久化的回复文本。

> `-N` 参数让 curl 不缓冲、实时输出 SSE。

---

## 7. POST /v1/responses(结构化、可保存状态)

OpenAI Responses API 格式。相比 chat/completions,它的优势是 **把工具调用过程结构化暴露出来**,并支持服务端保存多轮上下文。适合需要审计 Agent 每一步动作的对接方。

### 7.1 请求字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | 否 | 装饰性,同上。 |
| `input` | string / array | 是 | 用户输入内容。 |
| `instructions` | string | 否 | 系统指令(等价于 chat 里的 `system`)。 |
| `store` | boolean | 否 | 是否在服务端保存本次响应,供后续 `previous_response_id` 续接。 |
| `previous_response_id` | string | 否 | 上一次响应的 `id`,用于多轮续接(见 7.4)。 |
| `conversation` | string | 否 | 命名会话,自动续接同名会话的最新响应(见 7.5)。 |

### 7.2 请求示例

```json
{
  "model": "hermes-agent",
  "input": "我的项目目录里有哪些文件？",
  "instructions": "你是一个有帮助的编码助手。",
  "store": true
}
```

### 7.3 响应示例(注意 output 数组)

```json
{
  "id": "resp_abc123",
  "object": "response",
  "status": "completed",
  "model": "hermes-agent",
  "output": [
    {"type": "function_call", "name": "terminal", "arguments": "{\"command\": \"ls\"}", "call_id": "call_1"},
    {"type": "function_call_output", "call_id": "call_1", "output": "README.md src/ tests/"},
    {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "你的项目包含..."}]}
  ],
  "usage": {"input_tokens": 50, "output_tokens": 200, "total_tokens": 250}
}
```

`output` 是一个数组,按顺序记录 Agent 的每一步:

| `type` | 含义 |
|--------|------|
| `function_call` | Agent 调用了某个工具,`name`=工具名,`arguments`=传入参数。 |
| `function_call_output` | 该工具的执行结果。 |
| `message` | Agent 给用户的最终文本回复(在 `content[].text` 中)。 |

> **想让对接方看到"Agent 跑了什么命令、得到什么结果",用这个接口最直接。**

### 7.4 多轮续接(previous_response_id)

第二轮请求带上上一轮返回的 `id`,服务端会自动重建完整上下文(含此前所有工具调用与结果):

```json
{
  "input": "现在把 README 的内容展示给我",
  "previous_response_id": "resp_abc123"
}
```

### 7.5 命名会话(conversation)

不想自己跟踪 response id,可用 `conversation` 命名,服务端自动续接同名会话:

```json
{"input": "你好", "conversation": "my-project"}
{"input": "src/ 里有什么？", "conversation": "my-project"}
{"input": "跑一下测试", "conversation": "my-project"}
```

### 7.6 相关辅助接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/responses/{id}` | 按 ID 取回已保存的响应。 |
| `DELETE` | `/v1/responses/{id}` | 删除已保存的响应。 |

---

## 8. Runs API(长任务 + 事件订阅)

当任务较长、客户端希望**订阅进度事件**而非自己维护流式连接时,使用 Runs API。

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/v1/runs` | 创建一次运行,返回 `run_id`。请求体接受 `input` 及可选的 `session_id`、`instructions`、`conversation_history`、`previous_response_id`。 |
| `GET` | `/v1/runs/{run_id}` | 轮询运行状态(适合不想长连 SSE 的看板)。 |
| `GET` | `/v1/runs/{run_id}/events` | SSE 流:工具调用进度、token 增量、生命周期事件。支持断线重连。 |
| `POST` | `/v1/runs/{run_id}/stop` | 中断当前运行,立即返回 `{"status": "stopping"}`,Agent 会在下一个安全点停止。 |

创建运行的返回:

```json
{"run_id": "run_abc123", "status": "started"}
```

轮询状态的返回(状态值:`started` / `completed` / `failed` / `cancelled`):

```json
{
  "object": "hermes.run",
  "run_id": "run_abc123",
  "status": "completed",
  "session_id": "space-session",
  "model": "hermes-agent",
  "output": "Done.",
  "usage": {"input_tokens": 50, "output_tokens": 200, "total_tokens": 250}
}
```

---

## 9. 能力发现接口(对接方先打这几个)

**集成前建议先调用这些只读接口,自动探测本服务支持什么,而不要硬编码假设。** 均需 Bearer 鉴权。

### 9.1 GET /v1/capabilities

返回机器可读的能力清单,用于探测是否支持 runs、流式、取消、会话延续等:

```bash
curl http://<服务器地址>:8088/v1/capabilities \
  -H "Authorization: Bearer YOUR_API_SERVER_KEY"
```

```json
{
  "object": "hermes.api_server.capabilities",
  "platform": "hermes-agent",
  "model": "hermes-agent",
  "auth": {"type": "bearer", "required": true},
  "features": {
    "chat_completions": true,
    "responses_api": true,
    "run_submission": true,
    "run_status": true,
    "run_events_sse": true,
    "run_stop": true
  }
}
```

### 9.2 GET /v1/models

列出可用"模型"(默认 `hermes-agent`),多数前端用它做模型发现。

### 9.3 GET /v1/skills 与 GET /v1/toolsets

枚举 Agent 当前拥有的技能和工具集(只读):

```bash
# 技能列表
curl http://<服务器地址>:8088/v1/skills \
  -H "Authorization: Bearer YOUR_API_SERVER_KEY"
# → [{"name": "github-pr-workflow", "description": "...", "category": "..."}, ...]

# 工具集列表
curl http://<服务器地址>:8088/v1/toolsets \
  -H "Authorization: Bearer YOUR_API_SERVER_KEY"
# → [{"name": "core", "enabled": true, "configured": true, "tools": ["read_file", "write_file", ...]}, ...]
```

### 9.4 GET /health/detailed

扩展健康检查,额外报告活跃会话、运行中的 Agent、资源占用,适合监控/可观测性工具。

---

## 10. 会话管理接口(/api/sessions/*)

外部 UI 可通过 REST 管理会话,无需搭建 Dashboard。均需 Bearer 鉴权。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/sessions` | 列出会话(分页:`limit`、`offset`、`source`、`include_children`)。 |
| `POST` | `/api/sessions` | 创建空会话。 |
| `GET` | `/api/sessions/{id}` | 读取会话元数据。 |
| `PATCH` | `/api/sessions/{id}` | 更新标题或 `end_reason`。 |
| `DELETE` | `/api/sessions/{id}` | 删除会话。 |
| `GET` | `/api/sessions/{id}/messages` | 获取会话消息历史。 |
| `POST` | `/api/sessions/{id}/fork` | 分叉会话(等价 CLI 的 `/branch`)。 |
| `POST` | `/api/sessions/{id}/chat` | 在该会话中同步执行一轮。 |
| `POST` | `/api/sessions/{id}/chat/stream` | SSE 包装的单轮:推送 `assistant.delta`、`tool.started`、`tool.completed`、`run.completed` 事件。 |

---

## 11. 定时任务接口(/api/jobs)

远程管理 Agent 的定时/后台任务(等价 `hermes cron`)。均需 Bearer 鉴权。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/jobs` | 列出所有定时任务。 |
| `POST` | `/api/jobs` | 创建任务(body 接受 prompt、schedule、skills、provider 覆盖、投递目标)。 |
| `GET` | `/api/jobs/{job_id}` | 查看单个任务定义与上次运行状态。 |
| `PATCH` | `/api/jobs/{job_id}` | 更新任务字段(部分更新,合并)。 |
| `DELETE` | `/api/jobs/{job_id}` | 删除任务(并取消进行中的运行)。 |
| `POST` | `/api/jobs/{job_id}/pause` | 暂停任务(不删除)。 |
| `POST` | `/api/jobs/{job_id}/resume` | 恢复已暂停的任务。 |
| `POST` | `/api/jobs/{job_id}/run` | 立即触发运行(不等排期)。 |

---

## 12. 代码示例

### 12.1 Python(使用 OpenAI 官方 SDK)

最推荐的方式——把 base_url 指向本服务即可:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://<服务器地址>:8088/v1",
    api_key="YOUR_API_SERVER_KEY",
)

resp = client.chat.completions.create(
    model="hermes-agent",  # 装饰性,随意
    messages=[
        {"role": "user", "content": "列出当前目录的文件"}
    ],
)

print(resp.choices[0].message.content)
print("用量:", resp.usage.total_tokens)
```

### 12.2 Python(流式 + 工具进度)

```python
from openai import OpenAI

client = OpenAI(base_url="http://<服务器地址>:8088/v1", api_key="YOUR_API_SERVER_KEY")

stream = client.chat.completions.create(
    model="hermes-agent",
    messages=[{"role": "user", "content": "统计当前目录有多少个文件"}],
    stream=True,
)

for chunk in stream:
    delta = chunk.choices[0].delta
    if delta and delta.content:
        print(delta.content, end="", flush=True)
print()
```

### 12.3 Python(原生 requests,不依赖 SDK)

```python
import requests

url = "http://<服务器地址>:8088/v1/chat/completions"
headers = {
    "Authorization": "Bearer YOUR_API_SERVER_KEY",
    "Content-Type": "application/json",
}
payload = {
    "model": "hermes-agent",
    "messages": [{"role": "user", "content": "检查磁盘使用情况"}],
}

r = requests.post(url, headers=headers, json=payload, timeout=120)
r.raise_for_status()                      # 非 2xx 抛异常
data = r.json()
print(data["choices"][0]["message"]["content"])
```

### 12.4 Node.js(原生 fetch)

```javascript
const res = await fetch("http://<服务器地址>:8088/v1/chat/completions", {
  method: "POST",
  headers: {
    "Authorization": "Bearer YOUR_API_SERVER_KEY",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    model: "hermes-agent",
    messages: [{ role: "user", content: "列出当前目录的文件" }],
  }),
});

if (!res.ok) {
  throw new Error(`HTTP ${res.status}: ${await res.text()}`);
}
const data = await res.json();
console.log(data.choices[0].message.content);
```

### 12.5 curl(单行,避免续行符问题)

```bash
curl -X POST http://<服务器地址>:8088/v1/chat/completions -H "Authorization: Bearer YOUR_API_SERVER_KEY" -H "Content-Type: application/json" -d '{"model": "hermes-agent", "messages": [{"role": "user", "content": "你好"}]}'
```

> **提示**:多行 curl 用反斜杠 `\` 续行时,`\` 必须是该行最后一个字符,后面不能有任何空格,否则命令会被拆断报错。不确定时用单行最稳妥。

---

## 13. 错误处理

调用方应**先检查 HTTP 状态码,再决定解析 `choices`/`output` 还是 `error`**。

| 状态码 | 含义 | 常见原因 |
|--------|------|----------|
| `200` | 成功 | 正常返回结果。 |
| `400` | 请求格式错误 | 例如上传文件 / 非图片的 data URL,会返回 `unsupported_content_type`(本接口不支持文件上传)。 |
| `401` | 未授权 | 令牌缺失或错误,检查 `Authorization` 头是否与服务端一致。 |
| `405` | 方法不允许 | 用了错误的 HTTP 方法(如对只收 POST 的接口发了 GET),或请求体未正确发出。 |
| `5xx` | 服务端错误 | 服务异常,可重试或联系管理员。 |

错误响应为标准 OpenAI error 结构:

```json
{
  "error": {
    "message": "具体错误描述",
    "type": "错误类型",
    "code": "..."
  }
}
```

---

## 14. 已知限制

- **不支持文件上传**:`/v1/chat/completions` 与 `/v1/responses` 支持内联图片(`image_url`,可为 http(s) URL 或 `data:image/...`),但不支持文件上传(`file` / `input_file` / `file_id`)和非图片的 data URL。
- **`model` 字段是装饰性的**:实际大模型由服务端配置决定,客户端无法通过该字段切换。
- **响应保存上限**:用于 `previous_response_id` 续接的已存响应持久化在 SQLite 中(重启不丢),最多保留 100 条,超出按 LRU 淘汰。
- **响应耗时**:Agent 需思考并可能多次调用工具,单次请求耗时可能较长,客户端超时建议放宽。

---

## 15. 安全提醒(面向接入方)

- 本接口可让 Agent 在服务端执行**终端命令、读写文件**等高权限操作。请将 `API_SERVER_KEY` 视为与服务器登录凭据同级的敏感信息。
- 切勿将令牌提交到代码仓库、日志或前端可见处。
- 若浏览器需直接调用本接口,需服务端额外配置 CORS 白名单(`API_SERVER_CORS_ORIGINS`);服务器到服务器调用则无需 CORS。

---

*本文档基于 Hermes Agent 官方 API Server 规范整理。接口以服务端实际 `GET /v1/capabilities` 返回为准。*
