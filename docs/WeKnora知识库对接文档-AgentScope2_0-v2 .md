# WeKnora 知识库对接文档

> 面向 AgentScope 2.0 开发人员的 WeKnora 知识管理服务集成指南

\---

## 📋 版本变更说明（v2 相对于 v1 的新增内容）

本版本（v2）在 v1 基础上新增以下内容，均基于 WeKnora v0.7.2 实测验证：

|章节|变更类型|说明|
|-|-|-|
|**2.1 API 速查表**|新增|补充 `/files` 文件代理下载路由|
|**4.3 智能体对话（完整章节）**|🆕 全新|创建会话、Agent 对话 SSE 流式调用的完整说明，含请求参数、响应字段、Python 示例|
|**4.3.4 图片资源下载与渲染**|🆕 全新|`resource://` 句柄机制、三条文件路由对比、Python 下载示例、前端 Blob 渲染方案|
|**4.4 文件夹管理（完整章节）**|🆕 全新|v0.7.2 新增真实文件夹体系说明、`folder\_path` 字段变化、获取文件夹树接口、按文件夹过滤查询、上传时指定文件夹的新方式|
|**Q6: SSE 解析**|⚠️ 修正|原文档字段名 `type` 有误，实际为 `response\_type`，已更正并补充完整解析示例|
|**Q8～Q10**|🆕 全新|新增三条常见问题：API Key 权限、图片 404、`resource\_urls=public` 参数|
|**10. 错误码参考**|补充|新增图片下载相关的 403 错误说明|

\---

## 1\. 概览

### 1.1 WeKnora 提供什么

WeKnora 是一个完整的知识管理平台，为 AgentScope 2.0 智能体提供以下能力：

|能力|说明|
|-|-|
|**文档管理**|支持 PDF、Word、TXT、Markdown、HTML 等多种格式的知识入库|
|**URL 抓取**|从网页 URL 自动提取内容并入库|
|**混合检索**|向量检索 + 关键词检索，返回相关片段及溯源信息|
|**RAG 对话**|检索→重排→LLM 总结的完整流水线（SSE 流式返回）|
|**Agent 对话**|Agent 自主调用工具进行多步推理（SSE 流式返回）|
|**文件下载/预览**|原始文件下载与在线预览|
|**Wiki 生成**|基于知识库自动生成结构化 Wiki 页面|

### 1.2 服务地址与鉴权

|配置项|值|
|-|-|
|**Base URL**|`http://z2fpf345.tcp01.cn`|
|**API 前缀**|`/api/v1`|
|**API Key**|`<WEKNORA_API_KEY>`|
|**鉴权方式**|请求头 `X-API-Key: <your-api-key>`|
|**Content-Type**|`application/json`（文件上传为 `multipart/form-data`）|

> ⚠️ \*\*安全提醒\*\*：当前服务地址为 HTTP，API Key 会明文传输。\*\*生产环境强烈建议升级为 HTTPS\*\*。

### 1.3 核心概念说明

在对接前，请先区分以下三个概念——它们名称相近但用途完全不同：

|概念|是什么|格式示例|用途|
|-|-|-|-|
|**API Key**|租户级别的**鉴权密钥**（类似密码）|`<WEKNORA_API_KEY>`|放在请求头 `X-API-Key` 中，**每个请求都要带**，用于身份验证|
|**知识库 ID** (KB ID)|某个知识库的**唯一标识**|`a1b2c3d4-e5f6-7890-abcd-ef1234567890`|在 URL 路径或请求体中传入，表示"操作哪个知识库"|
|**知识 ID** (Knowledge ID)|某条知识（某个文件/URL/手动内容）的**唯一标识**|`kg-uuid-001`|用于获取知识详情、下载文件、查看分块等|

**获取方式**：

* **API Key**：在 WeKnora 管理界面 → 设置 → API 密钥中创建
* **知识库 ID**：调用 `GET /api/v1/knowledge-bases` 获取所有知识库列表，读取 `id` 字段
* **知识 ID**：调用 `GET /api/v1/knowledge-bases/:id/knowledge` 获取列表，或通过检索结果中的 `knowledge\_id` 字段获得

**类比理解**：

* API Key = 进入大楼的门禁卡（身份验证）
* 知识库 ID = 你要去的具体楼层/房间号
* 知识 ID = 房间里的具体某个文件柜

### 1.4 鉴权示例

```python
import requests

BASE\_URL = "http://z2fpf345.tcp01.cn/api/v1"
API\_KEY = "<WEKNORA_API_KEY>"

session = requests.Session()
session.headers.update({
    "X-API-Key": API\_KEY,
    "Content-Type": "application/json",
})
```

\---

## 2\. 核心 API 一览

### 2.1 API 速查表

|分类|方法|路径|用途|
|-|-|-|-|
|**知识库**|GET|`/knowledge-bases`|列出所有知识库|
||GET|`/knowledge-bases/:id`|获取知识库详情|
||POST|`/knowledge-bases/:id/hybrid-search`|**混合检索（核心）**|
|**知识管理**|POST|`/knowledge-bases/:id/knowledge/file`|上传文件创建知识|
||POST|`/knowledge-bases/:id/knowledge/url`|从 URL 创建知识|
||GET|`/knowledge-bases/:id/knowledge`|列出知识库中的知识|
||GET|`/knowledge/:id`|**获取知识详情（含文件信息）**|
||GET|`/knowledge/batch?ids=id1,id2`|**批量获取知识详情**|
||GET|`/knowledge/:id/download`|下载原始文件|
||GET|`/knowledge/:id/preview`|预览文件|
||DELETE|`/knowledge/:id`|删除知识|
|**分块管理**|GET|`/chunks/:knowledge\_id`|列出知识的文本分块|
|**会话**|POST|`/sessions`|创建对话会话|
||GET|`/sessions`|列出会话|
|**对话**|POST|`/knowledge-chat/:session\_id`|RAG 对话（SSE 流式）|
||POST|`/agent-chat/:session\_id`|Agent 对话（SSE 流式）|
|**文件代理**|GET|`/files?file\_path=resource://xxx`|**图片/文件代理下载**（根路径，非 `/api/v1`）🆕|
|**文件夹**|GET|`/knowledge-bases/:id/knowledge/folders`|获取文件夹树形结构 🆕|
||PUT|`/knowledge-bases/:id/knowledge/folders`|重命名/移动文件夹 🆕|
|**模型**|GET|`/models`|列出所有模型|
|**Agent**|GET|`/agents`|列出所有自定义 Agent|
||GET|`/agents/:id`|获取 Agent 详情|

\---

## 3\. 通用响应格式

所有 API 统一返回以下 JSON 结构：

```json
{
    "success": true,
    "data": { ... },      // 单个对象
    // 或
    "data": \[ ... ],      // 列表
    "message": "ok"
}
```

分页列表格式：

```json
{
    "success": true,
    "data": {
        "list": \[ ... ],
        "total": 100,
        "page": 1,
        "page\_size": 20
    }
}
```

错误响应：

```json
{
    "success": false,
    "message": "错误描述",
    "error": {
        "code": 404,
        "message": "Knowledge not found"
    }
}
```

\---

## 4\. 详细接口说明

### 4.1 知识库管理

#### 4.1.1 列出知识库（获取知识库 ID）

**对接第一步**：调用此接口获取当前租户下所有知识库的列表，从中取得 `id` 字段（即知识库 ID），后续所有操作（检索、上传、对话等）都需要用到它。

```
GET /api/v1/knowledge-bases
```

**curl 示例**：

```bash
curl -X GET "http://z2fpf345.tcp01.cn/api/v1/knowledge-bases" \\
  -H "X-API-Key: <WEKNORA_API_KEY>"
```

**Python 示例**：

```python
import requests

resp = requests.get(
    "http://z2fpf345.tcp01.cn/api/v1/knowledge-bases",
    headers={"X-API-Key": "<WEKNORA_API_KEY>"},
)
kbs = resp.json().get("data", \[])

for kb in kbs:
    print(f"ID: {kb\['id']}, 名称: {kb\['name']}, 描述: {kb.get('description', '')}")
```

**响应示例**：

```json
{
    "success": true,
    "data": \[
        {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "name": "产品知识库",
            "description": "包含所有产品文档",
            "created\_at": "2025-01-01T00:00:00Z",
            "updated\_at": "2025-06-01T00:00:00Z"
        },
        {
            "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
            "name": "FAQ 知识库",
            "description": "常见问题解答",
            "created\_at": "2025-03-01T00:00:00Z",
            "updated\_at": "2025-07-01T00:00:00Z"
        }
    ]
}
```

**响应字段说明**：

|字段|类型|说明|
|-|-|-|
|`id`|string|**知识库 ID**（UUID），后续所有接口都需要用到|
|`name`|string|知识库名称|
|`description`|string|知识库描述|
|`created\_at`|string|创建时间|
|`updated\_at`|string|最后更新时间|

**如何使用返回的知识库 ID**：

拿到 `id` 后，将其作为后续接口中的 `:id` 或 `kb\_id` 参数使用，例如：

```
# 混合检索 — 将 {id} 替换为实际的知识库 ID
POST /api/v1/knowledge-bases/a1b2c3d4-e5f6-7890-abcd-ef1234567890/hybrid-search

# 列出知识库中的知识
GET /api/v1/knowledge-bases/a1b2c3d4-e5f6-7890-abcd-ef1234567890/knowledge

# 上传文件到知识库
POST /api/v1/knowledge-bases/a1b2c3d4-e5f6-7890-abcd-ef1234567890/knowledge/file
```

#### 4.1.2 混合检索（⭐ 核心接口）

这是 AgentScope 最常用的接口——输入用户问题，返回最相关的知识片段及溯源信息。

```
POST /api/v1/knowledge-bases/:id/hybrid-search
```

**请求参数**：

```json
{
    "query\_text": "如何配置 VPN 连接？",
    "vector\_threshold": 0.5,
    "keyword\_threshold": 0.3,
    "match\_count": 5
}
```

|参数|类型|必填|默认值|说明|
|-|-|-|-|-|
|`query\_text`|string|✅|—|检索文本|
|`vector\_threshold`|float|❌|0.5|向量相似度阈值（0\~1）|
|`keyword\_threshold`|float|❌|0.3|关键词匹配阈值（0\~1）|
|`match\_count`|int|❌|5|返回结果数量|

**响应示例**：

```json
{
    "success": true,
    "data": \[
        {
            "id": "chunk-uuid-001",
            "content": "VPN 连接配置步骤：\\n1. 打开设置 > 网络 > VPN\\n2. 点击添加 VPN 配置...",
            "knowledge\_id": "kg-uuid-001",
            "knowledge\_title": "VPN 配置手册",
            "knowledge\_filename": "vpn-guide.pdf",
            "knowledge\_source": "",
            "knowledge\_channel": "web",
            "chunk\_index": 3,
            "start\_at": 1200,
            "end\_at": 1800,
            "score": 0.92,
            "match\_type": "vector",
            "chunk\_type": "text"
        },
        {
            "id": "chunk-uuid-002",
            "content": "VPN 常见问题排查...",
            "knowledge\_id": "kg-uuid-002",
            "knowledge\_title": "网络故障排查手册",
            "knowledge\_filename": "troubleshoot.docx",
            "knowledge\_source": "",
            "knowledge\_channel": "api",
            "chunk\_index": 7,
            "start\_at": 3400,
            "end\_at": 4100,
            "score": 0.78,
            "match\_type": "hybrid",
            "chunk\_type": "text"
        }
    ]
}
```

**搜索结果字段说明**：

|字段|类型|说明|
|-|-|-|
|`id`|string|Chunk ID|
|`content`|string|匹配的文本片段内容|
|`knowledge\_id`|string|**知识条目 ID**（用于获取文件详情和下载）|
|`knowledge\_title`|string|知识标题|
|`knowledge\_filename`|string|**原始文件名**|
|`knowledge\_source`|string|URL 来源（URL 类型知识有值）|
|`knowledge\_channel`|string|入库渠道（web/api/feishu/notion 等）|
|`chunk\_index`|int|分块在原文中的序号|
|`start\_at`|int|片段在原文中的起始字符位置|
|`end\_at`|int|片段在原文中的结束字符位置|
|`score`|float|相关度评分（越高越相关）|
|`match\_type`|string|匹配方式：`vector` / `keyword` / `hybrid`|
|`chunk\_type`|string|分块类型（text / image 等）|

\---

### 4.2 知识管理

#### 4.2.1 获取知识详情（含文件信息）

```
GET /api/v1/knowledge/:id
```

**响应示例**：

```json
{
    "success": true,
    "data": {
        "id": "kg-uuid-001",
        "knowledge\_base\_id": "kb-uuid-001",
        "type": "file",
        "title": "VPN 配置手册",
        "description": "",
        "file\_name": "vpn-guide.pdf",
        "file\_type": "pdf",
        "file\_size": 2048000,
        "file\_path": "local://1/abc123/vpn-guide.pdf",
        "file\_hash": "sha256:e3b0c44298fc1c14...",
        "source": "",
        "channel": "web",
        "parse\_status": "completed",
        "enable\_status": "enabled",
        "created\_at": "2025-06-01T00:00:00Z",
        "processed\_at": "2025-06-01T00:05:00Z"
    }
}
```

**文件相关字段**：

|字段|说明|
|-|-|
|`file\_name`|原始文件名|
|`file\_type`|文件类型（pdf / docx / md / txt / html 等）|
|`file\_size`|文件大小（bytes）|
|`file\_path`|存储路径（`provider://path` 格式）|
|`file\_hash`|文件哈希|
|`source`|URL 来源（URL 入库时有值，文件入库时为空）|

#### 4.2.2 批量获取知识详情

当搜索结果涉及多个知识文件时，使用批量接口减少请求次数：

```
GET /api/v1/knowledge/batch?ids=kg-uuid-001,kg-uuid-002,kg-uuid-003
```

**响应**：同 `GetKnowledge`，`data` 为数组。

#### 4.2.3 列出知识库中的知识

```
GET /api/v1/knowledge-bases/:id/knowledge?page=1\&page\_size=20
```

支持筛选参数：

|参数|类型|说明|
|-|-|-|
|`page`|int|页码，默认 1|
|`page\_size`|int|每页数量，默认 20|
|`keyword`|string|按文件名/标题关键词筛选|
|`file\_type`|string|按文件类型筛选|
|`parse\_status`|string|按解析状态筛选（pending/processing/completed/failed）|
|`source`|string|按来源渠道筛选（web/api/feishu/notion 等）|

#### 4.2.4 上传文件创建知识

```
POST /api/v1/knowledge-bases/:id/knowledge/file
Content-Type: multipart/form-data
```

|参数|类型|必填|说明|
|-|-|-|-|
|`file`|file|✅|上传的文件|
|`enable\_multimodel`|string|❌|是否启用多模态处理（默认 `true`）|

#### 4.2.5 从 URL 创建知识

```
POST /api/v1/knowledge-bases/:id/knowledge/url
```

```json
{
    "url": "https://example.com/docs/guide.html",
    "enable\_multimodel": true
}
```

#### 4.2.6 下载原始文件

```
GET /api/v1/knowledge/:id/download
```

**响应**：直接返回文件二进制流（`application/octet-stream`）。

#### 4.2.7 预览文件

```
GET /api/v1/knowledge/:id/preview
```

**响应**：返回文件预览内容。

\---

### 4.3 对话功能

#### 4.3.1 创建会话

在对话前需要先创建一个绑定知识库的会话：

```
POST /api/v1/sessions
```

```json
{
    "knowledge\_base\_id": "kb-uuid-001",
    "title": "产品咨询",
    "description": "客户产品使用咨询",
    "session\_strategy": {
        "max\_rounds": 10,
        "enable\_rewrite": true,
        "fallback\_strategy": "FIXED\_RESPONSE",
        "fallback\_response": "抱歉，我暂时无法回答这个问题。",
        "embedding\_top\_k": 10,
        "keyword\_threshold": 0.5,
        "vector\_threshold": 0.7,
        "summary\_model\_id": ""
    }
}
```

**响应**：

```json
{
    "success": true,
    "data": {
        "id": "session-uuid-001",
        "knowledge\_base\_id": "kb-uuid-001",
        "title": "产品咨询",
        "created\_at": "2025-08-10T00:00:00Z"
    }
}
```

#### 4.3.2 RAG 对话（知识问答）

```
POST /api/v1/knowledge-chat/:session\_id
```

**请求**：

```json
{
    "query": "如何配置 VPN？",
    "knowledge\_base\_ids": \["kb-uuid-001"],
    "web\_search\_enabled": false,
    "enable\_memory": false,
    "channel": "api"
}
```

|参数|类型|必填|说明|
|-|-|-|-|
|`query`|string|✅|用户问题|
|`knowledge\_base\_ids`|string\[]|❌|知识库 ID 列表（强烈建议提供）|
|`web\_search\_enabled`|bool|❌|是否启用联网搜索|
|`enable\_memory`|bool|❌|是否启用跨会话记忆|
|`channel`|string|❌|渠道标识，建议传 `"api"`|

**响应**（SSE 流式）：

```
data: {"response\_type": "answer", "content": "根据"}

data: {"response\_type": "answer", "content": "文档，VPN"}

data: {"response\_type": "answer", "content": "配置步骤如下..."}

data: {"response\_type": "references", "knowledge\_references": \[
    {"id": "chunk-001", "content": "...", "knowledge\_id": "kg-001", "knowledge\_title": "VPN手册", "score": 0.92}
]}

data: {"response\_type": "complete"}
```

|SSE 事件类型|说明|
|-|-|
|`answer`|LLM 回答片段（增量），拼接所有 `content` 即为完整回答|
|`references`|引用的知识片段列表，结构与混合检索结果一致|
|`error`|错误信息|
|`complete`|对话完成标志|

#### 4.3.3 Agent 对话（工具调用）🆕 详细说明

```
POST /api/v1/agent-chat/:session\_id
```

> \*\*与 RAG 对话的区别\*\*：Agent 对话会自主决策调用哪些工具（知识检索、联网搜索、图谱查询等），支持多步推理；RAG 对话是固定的"检索→总结"流水线。绑定了自定义智能体时，Agent 会使用该智能体配置的知识库范围和系统提示词。

**请求参数**：

```json
{
    "query": "项目当前有哪些未整改的安全隐患？",
    "agent\_enabled": true,
    "agent\_id": "be4c1c12-2c0f-4fd1-ac5c-0663bc86d356"
}
```

|参数|类型|必填|说明|
|-|-|-|-|
|`query`|string|✅|用户问题|
|`agent\_enabled`|bool|✅|是否启用 Agent 模式，固定传 `true`|
|`agent\_id`|string|✅|自定义智能体 UUID（在 WeKnora 智能体编辑页地址栏获取）|

> \*\*注意\*\*：`agent\_id` 对应的智能体已预配置可访问的知识库范围，不需要在请求中额外传 `knowledge\_base\_ids`。

**SSE 响应格式**：

```
event:message
data:{"id":"xxx","response\_type":"agent\_query","content":"","done":true,...}

event:message
data:{"id":"xxx","response\_type":"answer","content":"根据","done":false,...}

event:message
data:{"id":"xxx","response\_type":"answer","content":"检索结果，","done":false,...}

event:message
data:{"id":"xxx","response\_type":"answer","content":"...","done":true,...}

event:message
data:{"id":"xxx","response\_type":"session\_title","content":"会话标题","done":true,...}
```

**SSE 事件类型说明**：

|`response\_type`|`done`|说明|
|-|-|-|
|`agent\_query`|true|智能体正在执行工具调用（检索知识库等），done=true 表示查询阶段结束|
|`answer`|false|回答文字片段，逐步追加到完整回答中|
|`answer`|true|最后一个回答片段，表示本次回答完毕|
|`session\_title`|true|自动生成的会话标题，可用于更新 UI|

> ⚠️ \*\*重要\*\*：事件类型字段名是 \*\*`response\_type`\*\*，不是 `type`。原 v1 文档 Q6 中的示例代码有误，已在本版本修正。

**完整 Python 调用示例**：

```python
import requests
import json

BASE\_URL   = "http://z2fpf345.tcp01.cn/api/v1"
API\_KEY    = "sk-xxxxxxxx"   # 建议使用无知识库限制的 Key
AGENT\_ID   = "be4c1c12-2c0f-4fd1-ac5c-0663bc86d356"

def create\_session(agent\_id: str) -> str:
    """创建对话会话，返回 session\_id"""
    resp = requests.post(
        f"{BASE\_URL}/sessions",
        headers={"X-API-Key": API\_KEY, "Content-Type": "application/json"},
        json={"agent\_id": agent\_id},
    )
    resp.raise\_for\_status()
    return resp.json()\["data"]\["id"]


def agent\_chat(session\_id: str, agent\_id: str, query: str) -> str:
    """
    调用 Agent 对话，流式返回并拼接完整回答

    Returns:
        完整回答文本（含 resource:// 图片句柄）
    """
    resp = requests.post(
        f"{BASE\_URL}/agent-chat/{session\_id}",
        headers={
            "X-API-Key": API\_KEY,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        json={
            "query": query,
            "agent\_enabled": True,
            "agent\_id": agent\_id,
        },
        stream=True,
        timeout=120,
    )
    resp.raise\_for\_status()

    full\_answer = ""
    for line in resp.iter\_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if not line.startswith("data:"):   # 跳过 event:xxx 行
            continue
        try:
            event = json.loads(line\[5:].strip())
            if event.get("response\_type") == "answer":
                full\_answer += event.get("content", "")
                if event.get("done"):
                    break
        except json.JSONDecodeError:
            pass

    return full\_answer


# 使用示例
session\_id = create\_session(AGENT\_ID)
answer = agent\_chat(session\_id, AGENT\_ID, "项目当前有哪些未整改的安全隐患？")
print(answer)

# 多轮对话：复用同一 session\_id
answer2 = agent\_chat(session\_id, AGENT\_ID, "这些隐患的整改期限是多少？")
print(answer2)
```

#### 4.3.4 图片资源下载与渲染 🆕

Agent 回答中引用图片时使用内部句柄格式：

```markdown
!\[图片描述](resource://ZIYJD82lN2dDwtvvUrEd4Q)
```

`resource://` 句柄**不能直接在浏览器中访问**，需要通过文件代理接口下载。

**三条文件访问路由对比**：

|路由|用途|鉴权|备注|
|-|-|-|-|
|`GET /files?file\_path=resource://xxx`|图片/文件代理下载|`X-API-Key`（无限制 Key）|**根路径，不含 `/api/v1`**|
|`GET /api/v1/knowledge/:id/download`|下载知识库原始文件|`X-API-Key`|通过知识 ID 下载|
|`GET /r/:token`|短期公开 URL|token 本身鉴权|用于 IM 渠道图片外链|

> ⚠️ \*\*常见错误\*\*：`/files` 接口在\*\*根路径\*\*（`http://z2fpf345.tcp01.cn/files`），不是 `/api/v1/files`。调用 `/api/v1/files` 会返回 404。

**Python 示例：提取并下载所有图片**：

```python
import re

FILES\_BASE = "http://z2fpf345.tcp01.cn"   # 根路径

def download\_images(answer: str, save\_dir: str = ".") -> list\[str]:
    """
    从回答中提取 resource:// 句柄并下载图片

    注意：需要使用无知识库限制的 API Key
    """
    resource\_ids = re.findall(r'resource://(\[A-Za-z0-9\_\\-]+)', answer)
    saved = \[]

    for i, rid in enumerate(resource\_ids, 1):
        resp = requests.get(
            f"{FILES\_BASE}/files",             # ← 根路径，不是 /api/v1/files
            headers={"X-API-Key": API\_KEY},
            params={"file\_path": f"resource://{rid}"},
        )
        if resp.status\_code == 200:
            content\_type = resp.headers.get("Content-Type", "")
            ext = "jpg" if "jpeg" in content\_type else "png" if "png" in content\_type else "bin"
            path = f"{save\_dir}/image\_{i:02d}.{ext}"
            with open(path, "wb") as f:
                f.write(resp.content)
            saved.append(path)
            print(f"\[{i}] ✅ 已保存 {path}")
        else:
            print(f"\[{i}] ❌ 下载失败 {resp.status\_code}: resource://{rid}")

    return saved
```

**前端 Blob 渲染（JavaScript）**：

```javascript
const FILES\_BASE = "http://z2fpf345.tcp01.cn";
const API\_KEY = "sk-xxxxxxxx";

async function renderResourceImage(handle) {
    const resp = await fetch(
        `${FILES\_BASE}/files?file\_path=${encodeURIComponent('resource://' + handle)}`,
        { headers: { 'X-API-Key': API\_KEY } }
    );
    if (!resp.ok) return null;

    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);

    const img = document.createElement('img');
    img.src = blobUrl;
    img.onload = () => URL.revokeObjectURL(blobUrl); // 渲染后释放内存
    return img;
}

// 用法：从回答文本中提取并渲染所有图片
async function renderAllImages(answerText, container) {
    const regex = /!\\\[(\[^\\]]\*)\\]\\(resource:\\/\\/(\[A-Za-z0-9\_\\-]+)\\)/g;
    let match;
    while ((match = regex.exec(answerText)) !== null) {
        const \[\_, alt, handle] = match;
        const img = await renderResourceImage(handle);
        if (img) {
            img.alt = alt;
            container.appendChild(img);
        }
    }
}
```

\---

### 4.4 文件夹管理（v0.7.2 新增）🆕

WeKnora v0.7.2 引入了真实的文件夹体系，用专用的 `folder\_path` 字段存储目录路径，不再依赖文件名中的 `/` 前缀模拟目录。

#### 4.4.1 `folder\_path` 字段说明

v0.7.2 升级后，各接口对 `folder\_path` 的支持情况如下（实测验证）：

|接口|是否返回 `folder\_path`|说明|
|-|-|-|
|`GET /knowledge-bases/:id/knowledge`|✅ 返回|知识列表，每条文件都有 `folder\_path`|
|`GET /knowledge/:id`|✅ 返回|知识详情，包含完整 `folder\_path`|
|`GET /knowledge/batch`|✅ 返回|批量获取知识详情，包含 `folder\_path`|
|`POST /knowledge-bases/:id/hybrid-search`|❌ 不返回|检索结果为 chunk 级别，无 `folder\_path`|

**如需在检索结果中获取文件夹信息**，需要额外一步：拿到检索结果中的 `knowledge\_id`，再调用 `GET /knowledge/:id` 补充获取 `folder\_path`：

```python
def search\_with\_folder(kb\_id: str, query: str, top\_k: int = 5) -> list:
    """混合检索，并补充每条结果的文件夹路径"""
    # 第一步：混合检索
    resp = requests.post(
        f"{BASE\_URL}/knowledge-bases/{kb\_id}/hybrid-search",
        headers={"X-API-Key": API\_KEY},
        json={"query\_text": query, "match\_count": top\_k},
    )
    chunks = resp.json().get("data", \[])

    # 第二步：批量获取文件夹路径（去重后一次请求）
    knowledge\_ids = list({c\["knowledge\_id"] for c in chunks if c.get("knowledge\_id")})
    if knowledge\_ids:
        detail\_resp = requests.get(
            f"{BASE\_URL}/knowledge/batch",
            headers={"X-API-Key": API\_KEY},
            params={"ids": ",".join(knowledge\_ids)},
        )
        folder\_map = {
            d\["id"]: d.get("folder\_path", "")
            for d in detail\_resp.json().get("data", \[])
        }
        # 将 folder\_path 注入检索结果
        for chunk in chunks:
            chunk\["folder\_path"] = folder\_map.get(chunk.get("knowledge\_id"), "")

    return chunks
```

**知识列表接口和知识详情接口均返回 `folder\_path` 字段**，`file\_name` 字段也从"目录/文件名"拆分为只含文件名：

```json
{
    "id": "aaf02b17-f76d-4884-80fd-0b58dbdc77dd",
    "file\_name": "2、1#施工升降机计算书.docx",
    "folder\_path": "01\_合同图纸与方案/方案/真如医院项目施工升降机方案报监理/普陀区真如镇街道社区卫生服务中心异地扩建项目-施工升降机安拆方案",
    "title": "2、1#施工升降机计算书.docx",
    "parse\_status": "completed"
}
```

|字段|v0.7.1|v0.7.2|
|-|-|-|
|`file\_name`|`01\_合同图纸与方案/施工升降机计算书.docx`（含路径）|`施工升降机计算书.docx`（仅文件名）|
|`folder\_path`|不存在|`01\_合同图纸与方案/方案/...`（完整目录路径）|
|`title`|`01\_合同图纸与方案/施工升降机计算书.docx`|`01\_合同图纸与方案/施工升降机计算书.docx`（不变）|

#### 4.4.2 获取文件夹树形结构

```
GET /api/v1/knowledge-bases/:id/knowledge/folders
```

返回知识库的完整文件夹树，支持无限级嵌套，同时返回每个文件夹的文件数统计。

**响应示例**：

```json
{
    "success": true,
    "data": {
        "root\_document\_count": 0,
        "total\_document\_count": 877,
        "folders": \[
            {
                "path": "00\_项目总览",
                "name": "00\_项目总览",
                "document\_count": 1,
                "total\_count": 1
            },
            {
                "path": "01\_合同图纸与方案",
                "name": "01\_合同图纸与方案",
                "document\_count": 0,
                "total\_count": 623,
                "children": \[
                    {
                        "path": "01\_合同图纸与方案/图纸",
                        "name": "图纸",
                        "document\_count": 0,
                        "total\_count": 408,
                        "children": \[
                            {
                                "path": "01\_合同图纸与方案/图纸/人防图纸",
                                "name": "人防图纸",
                                "document\_count": 0,
                                "total\_count": 67
                            }
                        ]
                    }
                ]
            }
        ]
    }
}
```

**响应字段说明**：

|字段|类型|说明|
|-|-|-|
|`root\_document\_count`|int|根目录（无文件夹）的文件数|
|`total\_document\_count`|int|知识库全部文件总数|
|`folders\[].path`|string|文件夹完整路径（如 `01\_合同图纸与方案/图纸`）|
|`folders\[].name`|string|文件夹名称（末级目录名）|
|`folders\[].document\_count`|int|当前文件夹直接包含的文件数（不含子文件夹）|
|`folders\[].total\_count`|int|含子文件夹的总文件数|
|`folders\[].children`|array|子文件夹列表，结构与父级相同|

**Python 示例**：

```python
def get\_folder\_tree(kb\_id: str) -> dict:
    """获取知识库的文件夹树形结构"""
    resp = requests.get(
        f"{BASE\_URL}/knowledge-bases/{kb\_id}/knowledge/folders",
        headers={"X-API-Key": API\_KEY},
    )
    resp.raise\_for\_status()
    return resp.json()\["data"]


def flatten\_folders(tree: dict, prefix: str = "") -> list\[dict]:
    """将树形结构展平为列表，方便遍历"""
    result = \[]
    for folder in tree.get("folders", \[]):
        result.append({
            "path": folder\["path"],
            "name": folder\["name"],
            "total\_count": folder\["total\_count"],
        })
        if folder.get("children"):
            result.extend(flatten\_folders({"folders": folder\["children"]}))
    return result


# 使用示例
tree = get\_folder\_tree("b5796656-0456-423b-8d5f-f5936b5e3a3b")
print(f"知识库共 {tree\['total\_document\_count']} 个文件")
for folder in flatten\_folders(tree):
    print(f"  {folder\['path']}（{folder\['total\_count']} 个文件）")
```

#### 4.4.3 按文件夹过滤知识列表

获取指定文件夹下的文件，结合 `folder\_path` 参数使用：

```
GET /api/v1/knowledge-bases/:id/knowledge?folder\_path=04\_监测检测与试验\&folder\_recursive=true
```

|参数|类型|说明|
|-|-|-|
|`folder\_path`|string|文件夹路径（精确匹配，留空返回所有）|
|`folder\_recursive`|bool|`true` 则包含子文件夹；`false` 只返回当前层（默认 `true`）|

```python
def list\_knowledge\_in\_folder(kb\_id: str, folder\_path: str, recursive: bool = True) -> list:
    """获取指定文件夹内的所有文件"""
    resp = requests.get(
        f"{BASE\_URL}/knowledge-bases/{kb\_id}/knowledge",
        headers={"X-API-Key": API\_KEY},
        params={
            "folder\_path": folder\_path,
            "folder\_recursive": str(recursive).lower(),
            "page": 1,
            "page\_size": 100,
        },
    )
    resp.raise\_for\_status()
    return resp.json().get("data", \[])


# 只查 04\_监测检测与试验 目录下的文件
files = list\_knowledge\_in\_folder(
    "b5796656-0456-423b-8d5f-f5936b5e3a3b",
    "04\_监测检测与试验"
)
for f in files:
    print(f"{f\['folder\_path']} / {f\['file\_name']}")
```

#### 4.4.4 上传文件时指定文件夹（v0.7.2 新方式）

v0.7.2 新增 `folder\_path` 上传参数，不再需要把目录路径塞进文件名：

```python
# v0.7.1 旧方式（仍兼容，但不推荐）
data = {"fileName": "04\_监测检测与试验/监测报表76次.pdf"}

# v0.7.2 新方式（推荐）
data = {
    "fileName": "监测报表76次.pdf",   # 只填文件名
    "folder\_path": "04\_监测检测与试验",  # 目录路径单独传
}
```

\---

### 4.5 分块管理

#### 4.5.1 列出知识的文本分块

```
GET /api/v1/chunks/:knowledge\_id?page=1\&page\_size=20
```

**响应**：

```json
{
    "success": true,
    "data": {
        "list": \[
            {
                "id": "chunk-uuid-001",
                "knowledge\_id": "kg-uuid-001",
                "content": "第一章 概述\\n本文档介绍了...",
                "chunk\_index": 0,
                "start\_at": 0,
                "end\_at": 500,
                "is\_enabled": true,
                "created\_at": "2025-06-01T00:05:00Z"
            }
        ],
        "total": 25,
        "page": 1,
        "page\_size": 20
    }
}
```

\---

## 5\. AgentScope 2.0 集成方案

### 5.1 推荐架构

```
┌──────────┐    HTTPS    ┌────────────────────┐    HTTP     ┌───────────────┐
│ 终端用户  │◄───────────►│ AgentScope 2.0     │◄───────────►│  WeKnora      │
│ Web/APP  │             │ 后端服务器           │             │  知识库服务    │
└──────────┘             │                    │             └───────────────┘
                         │  ┌──────────────┐  │
                         │  │ Agent 编排层  │  │
                         │  │              │  │
                         │  │ ① 接收用户问题│  │
                         │  │ ② 调 WeKnora │  │
                         │  │   检索知识    │  │
                         │  │ ③ 组装 prompt │  │
                         │  │ ④ 调 LLM 生成 │  │
                         │  │ ⑤ 返回回答 +  │  │
                         │  │   引用溯源    │  │
                         │  └──────────────┘  │
                         └────────────────────┘
```

### 5.2 Python 封装类

```python
"""
WeKnora 知识库服务封装
适用于 AgentScope 2.0 Agent 的 tool 调用
"""

import json
import requests
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class WeKnoraConfig:
    """WeKnora 连接配置"""
    base\_url: str = "http://z2fpf345.tcp01.cn/api/v1"
    api\_key: str = ""
    timeout: int = 30        # 普通请求超时（秒）
    chat\_timeout: int = 300  # SSE 流式读取超时（秒）


@dataclass
class SearchReference:
    """检索引用"""
    knowledge\_id: str
    title: str
    filename: str
    source: str              # URL 来源
    content: str             # 匹配的文本片段
    score: float             # 相关度
    chunk\_index: int         # 原文中的分块序号
    start\_at: int            # 起始字符位置
    end\_at: int              # 结束字符位置
    match\_type: str          # vector / keyword / hybrid
    # 文件元信息（通过 get\_knowledge 补充）
    file\_name: str = ""
    file\_type: str = ""
    file\_size: int = 0
    file\_path: str = ""


class WeKnoraClient:
    """WeKnora REST API 客户端"""

    def \_\_init\_\_(self, config: WeKnoraConfig):
        self.config = config
        self.base\_url = config.base\_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": config.api\_key,
            "Content-Type": "application/json",
        })

    def \_get(self, path: str, params: dict = None) -> dict:
        resp = self.session.get(
            f"{self.base\_url}{path}",
            params=params,
            timeout=self.config.timeout,
        )
        resp.raise\_for\_status()
        return resp.json()

    def \_post(self, path: str, data: dict = None) -> dict:
        resp = self.session.post(
            f"{self.base\_url}{path}",
            json=data or {},
            timeout=self.config.timeout,
        )
        resp.raise\_for\_status()
        return resp.json()

    # ── 知识库 ─────────────────────────────────────────────

    def list\_knowledge\_bases(self) -> list:
        """列出所有知识库"""
        result = self.\_get("/knowledge-bases")
        return result.get("data", \[])

    # ── 检索 ───────────────────────────────────────────────

    def hybrid\_search(
        self,
        kb\_id: str,
        query: str,
        top\_k: int = 5,
        vector\_threshold: float = 0.5,
        keyword\_threshold: float = 0.3,
    ) -> List\[Dict\[str, Any]]:
        """
        混合检索（核心方法）

        Args:
            kb\_id: 知识库 ID
            query: 检索文本
            top\_k: 返回结果数
            vector\_threshold: 向量相似度阈值
            keyword\_threshold: 关键词匹配阈值

        Returns:
            搜索结果列表，每条包含 knowledge\_id, content, score 等
        """
        result = self.\_post(
            f"/knowledge-bases/{kb\_id}/hybrid-search",
            data={
                "query\_text": query,
                "vector\_threshold": vector\_threshold,
                "keyword\_threshold": keyword\_threshold,
                "match\_count": top\_k,
            },
        )
        return result.get("data", \[])

    # ── 知识详情 ───────────────────────────────────────────

    def get\_knowledge(self, knowledge\_id: str) -> dict:
        """
        获取知识详情（含 file\_path, file\_name, source 等文件信息）

        用于在前端展示原始文件信息、提供下载/预览链接
        """
        result = self.\_get(f"/knowledge/{knowledge\_id}")
        return result.get("data", {})

    def get\_knowledge\_batch(self, knowledge\_ids: List\[str]) -> list:
        """
        批量获取知识详情

        当搜索结果涉及多个知识文件时，一次性获取所有文件信息，
        减少请求次数。
        """
        if not knowledge\_ids:
            return \[]
        result = self.\_get(
            "/knowledge/batch",
            params={"ids": ",".join(knowledge\_ids)},
        )
        return result.get("data", \[])

    # ── 文件操作 ───────────────────────────────────────────

    def download\_file\_url(self, knowledge\_id: str) -> str:
        """获取原始文件下载 URL"""
        return f"{self.base\_url}/knowledge/{knowledge\_id}/download"

    def preview\_file\_url(self, knowledge\_id: str) -> str:
        """获取文件预览 URL"""
        return f"{self.base\_url}/knowledge/{knowledge\_id}/preview"

    def download\_file(self, knowledge\_id: str) -> bytes:
        """下载原始文件内容"""
        resp = self.session.get(
            f"{self.base\_url}/knowledge/{knowledge\_id}/download",
            timeout=self.config.timeout,
        )
        resp.raise\_for\_status()
        return resp.content

    # ── 知识入库 ───────────────────────────────────────────

    def upload\_file(self, kb\_id: str, file\_path: str, enable\_multimodal: bool = True) -> dict:
        """
        上传文件到知识库

        Args:
            kb\_id: 知识库 ID
            file\_path: 本地文件路径
            enable\_multimodal: 是否启用多模态处理
        """
        headers = {"X-API-Key": self.config.api\_key}
        # 移除 Content-Type，让 requests 自动设置 multipart boundary
        with open(file\_path, "rb") as f:
            resp = requests.post(
                f"{self.base\_url}/knowledge-bases/{kb\_id}/knowledge/file",
                headers=headers,
                files={"file": f},
                data={"enable\_multimodel": str(enable\_multimodal).lower()},
                timeout=self.config.timeout,
            )
        resp.raise\_for\_status()
        return resp.json()

    def create\_from\_url(self, kb\_id: str, url: str, enable\_multimodal: bool = True) -> dict:
        """从 URL 创建知识"""
        return self.\_post(
            f"/knowledge-bases/{kb\_id}/knowledge/url",
            data={"url": url, "enable\_multimodel": enable\_multimodal},
        )

    # ── 会话与对话 ─────────────────────────────────────────

    def create\_session(
        self,
        kb\_id: str,
        title: str = "",
        max\_rounds: int = 10,
    ) -> str:
        """
        创建对话会话，返回 session\_id
        """
        data = {
            "knowledge\_base\_id": kb\_id,
            "session\_strategy": {
                "max\_rounds": max\_rounds,
                "enable\_rewrite": True,
                "fallback\_strategy": "FIXED\_RESPONSE",
                "fallback\_response": "抱歉，我暂时无法回答这个问题。",
            },
        }
        if title:
            data\["title"] = title
        result = self.\_post("/sessions", data=data)
        return result.get("data", {}).get("id", "")

    def chat\_stream(self, session\_id: str, query: str, kb\_ids: List\[str] = None):
        """
        RAG 对话（SSE 流式）

        Yields:
            dict: {"type": "answer"|"references"|"complete", "content": ...}
        """
        body = {"query": query, "channel": "api"}
        if kb\_ids:
            body\["knowledge\_base\_ids"] = kb\_ids

        resp = self.session.post(
            f"{self.base\_url}/knowledge-chat/{session\_id}",
            json=body,
            stream=True,
            timeout=(10, self.config.chat\_timeout),
        )
        resp.raise\_for\_status()

        for raw\_line in resp.iter\_lines():
            if not raw\_line:
                continue
            if isinstance(raw\_line, bytes):
                raw\_line = raw\_line.decode("utf-8")
            if not raw\_line.startswith("data:"):
                continue
            payload = raw\_line\[5:].lstrip()
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue

            response\_type = event.get("response\_type", "")
            if response\_type == "answer":
                yield {"type": "answer", "content": event.get("content", "")}
            elif response\_type == "references":
                yield {"type": "references", "data": event.get("knowledge\_references", \[])}
            elif response\_type == "complete":
                yield {"type": "complete"}
                break
            elif response\_type == "error":
                yield {"type": "error", "content": event.get("content", "")}
                break


class WeKnoraKnowledgeTool:
    """
    AgentScope 2.0 Tool 封装

    将 WeKnora 封装为 Agent 可调用的 tool，
    返回检索结果 + 文件溯源信息供前端可视化。
    """

    def \_\_init\_\_(self, client: WeKnoraClient, default\_kb\_id: str = ""):
        self.client = client
        self.default\_kb\_id = default\_kb\_id

    def search(self, query: str, kb\_id: str = "", top\_k: int = 5) -> dict:
        """
        知识检索 tool

        供 AgentScope Agent 调用，返回检索片段和溯源信息。
        """
        target\_kb = kb\_id or self.default\_kb\_id
        if not target\_kb:
            return {"error": "未指定知识库 ID"}

        # 1. 混合检索
        results = self.client.hybrid\_search(target\_kb, query, top\_k=top\_k)

        # 2. 批量获取文件元信息
        knowledge\_ids = list({r.get("knowledge\_id") for r in results if r.get("knowledge\_id")})
        file\_info\_map = {}
        batch = self.client.get\_knowledge\_batch(knowledge\_ids)
        for kg in batch:
            file\_info\_map\[kg\["id"]] = {
                "file\_name": kg.get("file\_name", ""),
                "file\_type": kg.get("file\_type", ""),
                "file\_size": kg.get("file\_size", 0),
                "file\_path": kg.get("file\_path", ""),
                "source": kg.get("source", ""),
                "title": kg.get("title", ""),
                "download\_url": self.client.download\_file\_url(kg\["id"]),
                "preview\_url": self.client.preview\_file\_url(kg\["id"]),
            }

        # 3. 组装返回
        return {
            "query": query,
            "total": len(results),
            "references": \[
                {
                    "knowledge\_id": r.get("knowledge\_id", ""),
                    "title": r.get("knowledge\_title", ""),
                    "filename": r.get("knowledge\_filename", ""),
                    "content": r.get("content", ""),
                    "score": round(r.get("score", 0), 4),
                    "chunk\_index": r.get("chunk\_index", 0),
                    "start\_at": r.get("start\_at", 0),
                    "end\_at": r.get("end\_at", 0),
                    "match\_type": r.get("match\_type", ""),
                    "file\_info": file\_info\_map.get(r.get("knowledge\_id", ""), {}),
                }
                for r in results
            ],
        }
```

### 5.3 AgentScope 2.0 使用示例

```python
from agentscope.agents import AgentBase
from agentscope.message import Msg

# 初始化 WeKnora 客户端
client = WeKnoraClient(WeKnoraConfig(
    base\_url="http://z2fpf345.tcp01.cn/api/v1",
    api\_key="<WEKNORA_API_KEY>",
))

# 创建知识检索 tool
kb\_tool = WeKnoraKnowledgeTool(client, default\_kb\_id="your-kb-id")


class RAGAgent(AgentBase):
    """带知识库检索的 Agent"""

    def \_\_init\_\_(self, name: str, model\_config\_name: str, \*\*kwargs):
        super().\_\_init\_\_(name=name, model\_config\_name=model\_config\_name, \*\*kwargs)

    def reply(self, x: Msg = None) -> Msg:
        query = x.content

        # ① 检索知识
        search\_result = kb\_tool.search(query, top\_k=5)

        # ② 组装 prompt
        context\_parts = \[]
        references\_for\_frontend = \[]

        for ref in search\_result.get("references", \[]):
            context\_parts.append(
                f"\[来源: {ref\['filename']}] (相关度: {ref\['score']})\\n"
                f"{ref\['content']}"
            )
            references\_for\_frontend.append({
                "knowledge\_id": ref\["knowledge\_id"],
                "title": ref\["title"],
                "filename": ref\["filename"],
                "score": ref\["score"],
                "content\_snippet": ref\["content"]\[:200],
                "file\_info": ref\["file\_info"],
            })

        context = "\\n\\n---\\n\\n".join(context\_parts) if context\_parts else "（未检索到相关知识）"

        prompt = f"""基于以下知识库内容回答用户的问题。如果知识库中没有相关信息，请如实告知。

## 检索到的知识库内容

{context}

## 用户问题

{query}

## 回答"""

        # ③ 调用 LLM
        response = self.model(prompt)

        # ④ 返回回答（附带引用信息，前端可用于可视化）
        return Msg(
            name=self.name,
            content=response.text,
            metadata={"references": references\_for\_frontend},  # 引用溯源
        )
```

### 5.4 前端可视化数据结构

Agent 返回的 `references` 数组可直接用于前端知识库资料可视化：

```typescript
// 前端 TypeScript 类型定义
interface KnowledgeReference {
    knowledge\_id: string;
    title: string;           // 知识标题
    filename: string;        // 原始文件名
    score: number;           // 相关度评分
    content\_snippet: string; // 匹配的文本片段（前 200 字）
    file\_info: {
        file\_name: string;   // 文件名
        file\_type: string;   // 文件类型（pdf/docx/md...）
        file\_size: number;   // 文件大小（bytes）
        file\_path: string;   // 存储路径
        source: string;      // URL 来源
        title: string;       // 知识标题
        download\_url: string;// 下载链接（需后端代理）
        preview\_url: string; // 预览链接（需后端代理）
    };
}
```

**前端可视化建议**：

|可视化元素|实现方式|
|-|-|
|引用来源列表|显示 `filename` + `score`|
|文件类型图标|根据 `file\_type` 显示对应图标|
|文本片段预览|显示 `content\_snippet`，高亮关键词|
|原始文件下载|调后端代理接口转发 `download\_url`|
|文件在线预览|后端代理转发 `preview\_url`|
|URL 来源跳转|当 `source` 非空时显示外链图标|
|相关度排序|按 `score` 降序排列|

\---

## 6\. 文件路径披露（知识库资料可视化）

AgentScope 前端需要展示知识库中的文件信息（文件名、大小、类型、来源等），甚至提供原始文件下载。本节说明如何从 WeKnora 获取这些文件元信息。

### 6.1 数据流转概览

```
┌────────────────────────────────────────────────────────────────────────┐
│  AgentScope 前端                                                       │
│                                                                        │
│  用户看到：                                                            │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ 📄 vpn-guide.pdf    (2.0 MB)   相关度: 0.92     \[下载] \[预览]  │  │
│  │ 📄 troubleshoot.docx (800 KB)   相关度: 0.78     \[下载] \[预览]  │  │
│  │ 🌐 https://example.com/guide                                    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                     ▲                                                  │
│                     │ 展示 file\_name, file\_type, file\_size, source     │
│                     │                                                  │
│  AgentScope 后端    │                                                  │
│  ┌──────────────┐   │                                                  │
│  │ 1. 调 hybrid-search → 拿到 knowledge\_id                            │
│  │ 2. 调 GET /knowledge/batch?ids=... → 拿到文件元信息                 │
│  │ 3. 组装 references 返回给前端                                       │
│  └──────────────┘                                                      │
└────────────────────────────────────────────────────────────────────────┘
```

### 6.2 第一步：从检索结果获取 knowledge\_id

调用混合检索接口后，每条结果都包含 `knowledge\_id`：

```python
results = client.hybrid\_search(kb\_id="your-kb-id", query="如何配置 VPN？", top\_k=5)

# 提取所有 knowledge\_id（去重）
knowledge\_ids = list(set(r\["knowledge\_id"] for r in results))
# 示例输出: \["kg-uuid-001", "kg-uuid-002"]
```

### 6.3 第二步：批量获取文件元信息

通过 `GET /api/v1/knowledge/batch` 一次性获取所有文件详情：

```python
# 批量获取文件元信息
resp = session.get(
    f"{BASE\_URL}/knowledge/batch",
    params={"ids": ",".join(knowledge\_ids)},
)
knowledge\_list = resp.json().get("data", \[])
```

**每条知识返回的文件相关字段**：

```json
{
    "id": "kg-uuid-001",
    "title": "VPN 配置手册",
    "file\_name": "vpn-guide.pdf",
    "file\_type": "pdf",
    "file\_size": 2097152,
    "file\_path": "local://1/abc123/vpn-guide.pdf",
    "file\_hash": "sha256:e3b0c44298fc1c14...",
    "source": "",
    "type": "file",
    "channel": "web",
    "parse\_status": "completed"
}
```

**文件相关字段详解**：

|字段|类型|说明|前端用途|
|-|-|-|-|
|`file\_name`|string|原始文件名（含扩展名）|展示文件名|
|`file\_type`|string|文件类型（pdf / docx / md / txt / html / csv / xlsx 等）|显示文件类型图标|
|`file\_size`|int|文件大小（字节）|展示文件大小（需转换 KB/MB）|
|`file\_path`|string|存储路径（`provider://path` 格式）|内部标识，一般不直接暴露给前端|
|`file\_hash`|string|文件内容哈希（SHA-256）|去重校验|
|`source`|string|URL 来源。文件上传时为空字符串；URL 抓取时为原始 URL|URL 类型知识展示来源链接|
|`type`|string|知识类型：`file` / `url` / `manual`|区分知识来源类型|
|`channel`|string|入库渠道：`web` / `api` / `feishu` / `notion` 等|展示入库来源|
|`parse\_status`|string|解析状态：`pending` / `processing` / `completed` / `failed`|展示处理状态|

### 6.4 第三步：组装前端可视化数据

```python
def build\_visualization\_data(search\_results, knowledge\_list):
    """将检索结果和文件元信息组装为前端可直接使用的结构"""

    # 建立 knowledge\_id → 文件元信息 的映射
    kg\_map = {kg\["id"]: kg for kg in knowledge\_list}

    references = \[]
    for r in search\_results:
        kg\_id = r.get("knowledge\_id", "")
        kg\_info = kg\_map.get(kg\_id, {})

        references.append({
            # ── 检索片段信息 ──
            "knowledge\_id": kg\_id,
            "title": r.get("knowledge\_title", ""),
            "content\_snippet": r.get("content", "")\[:200],
            "score": r.get("score", 0),
            "chunk\_index": r.get("chunk\_index", 0),
            "match\_type": r.get("match\_type", ""),

            # ── 文件元信息（前端展示用）──
            "file\_name": kg\_info.get("file\_name", ""),
            "file\_type": kg\_info.get("file\_type", ""),
            "file\_size": kg\_info.get("file\_size", 0),
            "file\_path": kg\_info.get("file\_path", ""),
            "source": kg\_info.get("source", ""),
            "knowledge\_type": kg\_info.get("type", ""),  # file / url / manual
            "parse\_status": kg\_info.get("parse\_status", ""),

            # ── 操作链接（需后端代理，见第 8 节）──
            "download\_url": f"/api/files/download/{kg\_id}",
            "preview\_url": f"/api/files/preview/{kg\_id}",
        })

    return references
```

### 6.5 前端展示示例

```typescript
// 文件大小格式化
function formatFileSize(bytes: number): string {
    if (bytes === 0) return "—";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 \* 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 \* 1024)).toFixed(1) + " MB";
}

// 根据 file\_type 返回图标
function getFileIcon(fileType: string): string {
    const iconMap: Record<string, string> = {
        pdf: "📕",
        docx: "📘", doc: "📘",
        xlsx: "📗", xls: "📗", csv: "📗",
        pptx: "📙", ppt: "📙",
        md: "📝", txt: "📄",
        html: "🌐",
    };
    return iconMap\[fileType] || "📄";
}

// 根据 knowledge\_type 和 source 决定展示内容
function renderReference(ref: KnowledgeReference) {
    if (ref.knowledge\_type === "url" \&\& ref.source) {
        // URL 类型：展示来源链接
        return `<a href="${ref.source}" target="\_blank">${ref.source}</a>`;
    }
    // 文件类型：展示文件名 + 大小
    return `${getFileIcon(ref.file\_type)} ${ref.file\_name} (${formatFileSize(ref.file\_size)})`;
}
```

### 6.6 单个知识详情查询

如果只需要查某个知识的文件信息：

```
GET /api/v1/knowledge/:id
```

```python
# 获取单个知识的完整信息
resp = session.get(f"{BASE\_URL}/knowledge/{knowledge\_id}")
knowledge = resp.json().get("data", {})

print(f"文件名: {knowledge\['file\_name']}")
print(f"类型: {knowledge\['file\_type']}")
print(f"大小: {knowledge\['file\_size']} bytes")
print(f"存储路径: {knowledge\['file\_path']}")
print(f"来源: {knowledge\['source']}")
```

\---

## 7\. 文件上传与解析

AgentScope 前端用户可以选择本地文件上传到 WeKnora 知识库，WeKnora 会自动完成解析、分块、向量化，使文件内容可被检索。

### 7.1 整体流程

```
┌────────────────┐         ┌──────────────────┐         ┌──────────────┐
│  AgentScope    │  ①上传   │  AgentScope      │  ②转发   │  WeKnora     │
│  前端           │────────►│  后端             │────────►│  :8080       │
│  (用户浏览器)   │  file   │  (代理转发)       │ multipart│              │
└────────────────┘         └──────────────────┘         └──────┬───────┘
                                                               │
                                                               │ ③ 异步解析流水线
                                                               ▼
                                                      ┌────────────────┐
                                                      │ 文档解析        │
                                                      │ → 分块 (Chunk)  │
                                                      │ → Embedding    │
                                                      │ → 存入向量库    │
                                                      └────────────────┘
```

**关键说明**：

* WeKnora 的文件上传是**异步解析**的：上传成功后立即返回 `knowledge\_id`，后台异步进行文档解析→分块→向量化
* 解析状态通过 `parse\_status` 字段跟踪：`pending` → `processing` → `finalizing` → `completed`（或 `failed`）
* 只有 `parse\_status = "completed"` 的知识才能被检索到

### 7.2 上传接口

```
POST /api/v1/knowledge-bases/:id/knowledge/file
Content-Type: multipart/form-data
```

**请求参数（form-data）**：

|参数|类型|必填|说明|
|-|-|-|-|
|`file`|File|✅|上传的文件（最大 50MB，可通过 `MAX\_FILE\_SIZE\_MB` 环境变量调整）|
|`enable\_multimodel`|string|❌|是否启用多模态处理（图片 OCR 等），默认 `"true"`|
|`fileName`|string|❌|自定义文件名（可选，用于保留文件夹路径结构）|
|`metadata`|string|❌|JSON 字符串格式的自定义元数据（可选）|
|`tag\_ids`|string|❌|逗号分隔的标签 ID（可选，用于知识分类）|
|`channel`|string|❌|入库渠道标识，建议传 `"api"`|
|`process\_config`|string|❌|JSON 字符串，覆盖默认解析配置（可选）|

**支持的文件格式**：PDF、DOCX、DOC、TXT、Markdown、HTML、CSV、XLSX、PPTX 等常见文档格式。

### 7.3 响应格式

上传成功返回 HTTP 200：

```json
{
    "success": true,
    "data": {
        "id": "kg-new-uuid-001",
        "knowledge\_base\_id": "kb-uuid-001",
        "title": "新上传的产品手册.pdf",
        "file\_name": "新上传的产品手册.pdf",
        "file\_type": "pdf",
        "file\_size": 1536000,
        "file\_path": "local://1/def456/新上传的产品手册.pdf",
        "parse\_status": "pending",
        "created\_at": "2025-08-10T10:00:00Z"
    }
}
```

> 注意：上传成功后 `parse\_status` 为 `"pending"`，表示正在等待后台解析。

### 7.4 完整上传代码示例

#### 方式一：AgentScope 后端直接代理（推荐）

由于 WeKnora 不直接面向终端用户，AgentScope 后端需要作为代理转发文件上传：

```python
from fastapi import FastAPI, UploadFile, File, Form
import requests

app = FastAPI()

WEKNORA\_BASE\_URL = "http://z2fpf345.tcp01.cn/api/v1"
WEKNORA\_API\_KEY = "<WEKNORA_API_KEY>"


@app.post("/api/knowledge/upload")
async def upload\_to\_weknora(
    kb\_id: str = Form(...),               # 目标知识库 ID
    file: UploadFile = File(...),          # 用户上传的文件
    enable\_multimodel: bool = Form(True),  # 是否启用多模态
):
    """
    代理文件上传到 WeKnora

    前端 (用户浏览器) → AgentScope 后端 → WeKnora
    """
    # 读取文件内容
    file\_content = await file.read()

    # 构造 multipart/form-data 请求转发到 WeKnora
    resp = requests.post(
        f"{WEKNORA\_BASE\_URL}/knowledge-bases/{kb\_id}/knowledge/file",
        headers={"X-API-Key": WEKNORA\_API\_KEY},
        files={"file": (file.filename, file\_content, file.content\_type)},
        data={
            "enable\_multimodel": str(enable\_multimodel).lower(),
            "channel": "api",  # 标记来源渠道
        },
        timeout=120,
    )
    resp.raise\_for\_status()
    result = resp.json()

    return {
        "success": True,
        "knowledge\_id": result.get("data", {}).get("id", ""),
        "file\_name": result.get("data", {}).get("file\_name", ""),
        "parse\_status": result.get("data", {}).get("parse\_status", ""),
        "message": "文件上传成功，正在后台解析中...",
    }
```

#### 方式二：Python SDK 直接调用

```python
def upload\_file\_to\_weknora(
    kb\_id: str,
    file\_path: str,
    enable\_multimodel: bool = True,
    custom\_filename: str = "",
) -> dict:
    """
    上传本地文件到 WeKnora 知识库

    Args:
        kb\_id: 知识库 ID
        file\_path: 本地文件路径
        enable\_multimodel: 是否启用多模态（图片 OCR 等）
        custom\_filename: 自定义文件名（可选）

    Returns:
        创建的知识条目信息，包含 knowledge\_id 和 parse\_status
    """
    headers = {"X-API-Key": API\_KEY}

    with open(file\_path, "rb") as f:
        files = {"file": f}
        data = {
            "enable\_multimodel": str(enable\_multimodel).lower(),
            "channel": "api",
        }
        if custom\_filename:
            data\["fileName"] = custom\_filename

        resp = requests.post(
            f"{BASE\_URL}/knowledge-bases/{kb\_id}/knowledge/file",
            headers=headers,
            files=files,
            data=data,
            timeout=120,
        )

    resp.raise\_for\_status()
    result = resp.json()

    if not result.get("success"):
        raise Exception(f"上传失败: {result.get('message', '未知错误')}")

    knowledge = result.get("data", {})
    return {
        "knowledge\_id": knowledge.get("id"),
        "file\_name": knowledge.get("file\_name"),
        "file\_size": knowledge.get("file\_size"),
        "parse\_status": knowledge.get("parse\_status"),  # pending
    }
```

### 7.5 跟踪解析状态

上传后需要轮询解析状态，直到文件处理完成：

```python
import time

def wait\_for\_parse\_complete(knowledge\_id: str, timeout\_seconds: int = 300) -> dict:
    """
    轮询等待知识解析完成

    Args:
        knowledge\_id: 知识 ID
        timeout\_seconds: 最大等待时间（秒）

    Returns:
        最终的知识详情（parse\_status = completed 或 failed）
    """
    start\_time = time.time()
    poll\_interval = 3  # 每 3 秒轮询一次

    while time.time() - start\_time < timeout\_seconds:
        resp = session.get(f"{BASE\_URL}/knowledge/{knowledge\_id}")
        knowledge = resp.json().get("data", {})
        status = knowledge.get("parse\_status", "")

        if status == "completed":
            print(f"✅ 解析完成: {knowledge.get('file\_name')}")
            return knowledge
        elif status == "failed":
            error\_msg = knowledge.get("error\_message", "未知错误")
            raise Exception(f"❌ 解析失败: {error\_msg}")
        elif status in ("pending", "processing", "finalizing"):
            print(f"⏳ 解析中... 当前状态: {status}")
            time.sleep(poll\_interval)
        else:
            print(f"⚠️ 未知状态: {status}")
            time.sleep(poll\_interval)

    raise TimeoutError(f"解析超时（{timeout\_seconds}秒）")
```

### 7.6 从 URL 创建知识

除了文件上传，也可以让 WeKnora 直接抓取网页内容：

```
POST /api/v1/knowledge-bases/:id/knowledge/url
Content-Type: application/json
```

```json
{
    "url": "https://example.com/docs/guide.html",
    "enable\_multimodel": true,
    "file\_name": "产品指南",
    "title": "产品使用指南",
    "tag\_ids": \["tag-uuid-001"],
    "channel": "api"
}
```

```python
def create\_knowledge\_from\_url(kb\_id: str, url: str, title: str = "") -> dict:
    """从 URL 创建知识"""
    data = {
        "url": url,
        "enable\_multimodel": True,
        "channel": "api",
    }
    if title:
        data\["title"] = title

    resp = session.post(f"{BASE\_URL}/knowledge-bases/{kb\_id}/knowledge/url", json=data)
    resp.raise\_for\_status()
    result = resp.json()

    return {
        "knowledge\_id": result.get("data", {}).get("id"),
        "title": result.get("data", {}).get("title"),
        "parse\_status": result.get("data", {}).get("parse\_status"),
    }
```

### 7.7 完整流程示例：上传 → 等待 → 检索

```python
def full\_upload\_and\_search\_workflow(kb\_id: str, file\_path: str, query: str):
    """
    完整流程演示：上传文件 → 等待解析 → 检索内容
    """
    # ① 上传文件
    print("📤 上传文件...")
    upload\_result = upload\_file\_to\_weknora(kb\_id, file\_path)
    knowledge\_id = upload\_result\["knowledge\_id"]
    print(f"   知识 ID: {knowledge\_id}")
    print(f"   解析状态: {upload\_result\['parse\_status']}")

    # ② 等待解析完成
    print("\\n⏳ 等待解析...")
    knowledge = wait\_for\_parse\_complete(knowledge\_id)
    print(f"   ✅ 解析完成！文件名: {knowledge\['file\_name']}")
    print(f"   文件大小: {knowledge\['file\_size']} bytes")
    print(f"   存储路径: {knowledge\['file\_path']}")

    # ③ 检索内容
    print(f"\\n🔍 检索: {query}")
    results = client.hybrid\_search(kb\_id, query, top\_k=3)

    for r in results:
        print(f"\\n   📄 {r\['knowledge\_filename']} (相关度: {r\['score']:.2f})")
        print(f"   片段: {r\['content']\[:100]}...")

    return results
```

### 7.8 上传常见问题

|问题|原因与解决|
|-|-|
|`文件大小不能超过50MB`|默认限制 50MB。如需调大，需修改 WeKnora 服务器 `MAX\_FILE\_SIZE\_MB` 环境变量并重启|
|`File upload failed`|请求格式不是 `multipart/form-data`，或 `file` 字段名写错|
|上传成功但检索不到|文件还在解析中，检查 `parse\_status` 是否为 `completed`|
|`Unauthorized`|API Key 无效或没有该知识库的写入权限|
|URL 抓取失败|URL 不可访问，或被 WeKnora 的 SSRF 安全策略拦截|

\---

## 8\. 文件下载代理

由于 WeKnora 不直接面向终端用户，**前端下载/预览文件需要在 AgentScope 后端加代理接口**：

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.get("/api/files/download/{knowledge\_id}")
async def proxy\_download(knowledge\_id: str):
    """代理 WeKnora 文件下载"""
    resp = requests.get(
        client.download\_file\_url(knowledge\_id),
        headers={"X-API-Key": client.config.api\_key},
        stream=True,
    )
    resp.raise\_for\_status()
    return StreamingResponse(
        resp.iter\_content(chunk\_size=8192),
        media\_type=resp.headers.get("Content-Type", "application/octet-stream"),
    )

@app.get("/api/files/preview/{knowledge\_id}")
async def proxy\_preview(knowledge\_id: str):
    """代理 WeKnora 文件预览"""
    resp = requests.get(
        client.preview\_file\_url(knowledge\_id),
        headers={"X-API-Key": client.config.api\_key},
    )
    resp.raise\_for\_status()
    return resp.json()
```

\---

## 9\. 常见问题

### Q1: 如何获取 API Key？

登录 WeKnora 管理界面 → 设置 → API 密钥 → 创建新的 API Key。

当前已创建的可用 Key：`<WEKNORA_API_KEY>`

> ⚠️ 注意：API Key 是\*\*租户级别的鉴权密钥\*\*，不是知识库 ID。知识库 ID 需要通过 `GET /api/v1/knowledge-bases` 接口获取。详见 \[1.3 核心概念说明](#13-核心概念说明)。

### Q2: 知识库 ID 怎么获取？

调用 `GET /api/v1/knowledge-bases` 获取所有知识库列表，从中找到 `id` 字段。

### Q3: 搜索结果中的 knowledge\_id 和 knowledge\_filename 有什么区别？

* `knowledge\_id`：知识条目的唯一标识（UUID），用于调 API 获取详情、下载文件等
* `knowledge\_filename`：原始文件名（如 `vpn-guide.pdf`），仅用于展示

### Q4: 如何判断一个知识是文件上传的还是 URL 抓取的？

查看 `Knowledge.source` 字段：

* 为空字符串 `""`：文件上传
* 有 URL 值：从 URL 抓取
* 值为 `"manual"`：手动创建的 Markdown 知识

### Q5: RAG 对话和混合检索的区别？

||混合检索|RAG 对话|
|-|-|-|
|返回内容|原始文本片段|LLM 总结后的回答 + 引用|
|是否需要会话|❌ 不需要|✅ 需要 session\_id|
|是否消耗 LLM|❌|✅|
|适用场景|Agent 自行组装 prompt|直接获取答案|
|推荐用法|⭐ AgentScope 推荐|快速原型验证|

**AgentScope 推荐使用混合检索**：Agent 拿到检索片段后自行组装 prompt 调用 LLM，这样对推理流程有完全的控制权。

### Q6: SSE 流式对话如何解析？

> ⚠️ \*\*v1 文档勘误\*\*：原文档示例中使用 `chunk\["type"]` 判断事件类型，\*\*实际字段名为 `response\_type`，不是 `type`\*\*。使用 `type` 会导致所有条件判断失效，输出为空。

WeKnora 的 SSE 每行格式为：

```
event:message
data:{"id":"...","response\_type":"answer","content":"片段","done":false,...}
```

正确解析方式（需跳过 `event:xxx` 行，只处理 `data:` 行）：

```python
import requests
import json

def stream\_agent\_chat(base\_url, api\_key, session\_id, agent\_id, query):
    """
    调用 Agent 对话接口并解析 SSE 流式响应

    注意：事件类型字段名是 response\_type，不是 type
    """
    resp = requests.post(
        f"{base\_url}/agent-chat/{session\_id}",
        headers={
            "X-API-Key": api\_key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        json={
            "query": query,
            "agent\_enabled": True,
            "agent\_id": agent\_id,
        },
        stream=True,
        timeout=120,
    )

    full\_answer = ""
    for line in resp.iter\_lines():
        if not line:
            continue
        line = line.decode("utf-8")

        # 跳过 event:xxx 行，只处理 data: 行
        if not line.startswith("data:"):
            continue

        try:
            event = json.loads(line\[5:].strip())
            response\_type = event.get("response\_type", "")  # ← 注意是 response\_type
            content = event.get("content", "")
            done = event.get("done", False)

            if response\_type == "answer" and content:
                print(content, end="", flush=True)
                full\_answer += content

            if response\_type == "answer" and done:
                print("\\n\[完成]")
                break

        except json.JSONDecodeError:
            pass

    return full\_answer
```

**SSE 事件类型说明**：

|`response\_type` 值|说明|
|-|-|
|`agent\_query`|智能体正在执行工具调用（如检索知识库），`done:true` 时表示查询结束|
|`answer`|回答文字片段，逐步拼接；`done:true` 表示回答完毕|
|`session\_title`|会话标题（自动生成），可用于更新 UI 标题栏|

### Q7: 文件上传有什么限制？

通过 WeKnora 管理界面查看具体限制。常见支持格式：PDF、DOCX、TXT、MD、HTML、CSV、XLSX 等。

### Q8: 调用 `/files` 下载图片返回 403，怎么解决？🆕

原因：使用了**知识库限制型 API Key**。此类 Key 被限制只能访问特定知识库的文本内容，无法访问 `/files` 文件代理接口（WeKnora 出于安全考虑，防止通过文件代理绕过知识库访问控制）。

解决方案：在 WeKnora 管理界面 → 设置 → API Keys → 新建一个**不勾选知识库限制**的 Key，用该 Key 调用文件下载接口。

### Q9: 回答中图片显示为 `resource://xxx`，如何渲染成真实图片？🆕

WeKnora 回答中的图片引用格式为 `resource://` 内部句柄，不能直接作为 `<img src>` 使用。需要通过以下步骤渲染：

**注意：`/files` 接口在根路径，不在 `/api/v1/` 下。**

```python
import requests
import re

def download\_images\_from\_answer(answer: str, files\_base: str, api\_key: str, save\_dir: str = "."):
    """
    从回答中提取 resource:// 句柄并下载图片

    Args:
        answer:     智能体的完整回答文本
        files\_base: 文件服务根地址，如 http://z2fpf345.tcp01.cn
        api\_key:    无知识库限制的 API Key
        save\_dir:   图片保存目录
    """
    resource\_ids = re.findall(r'resource://(\[A-Za-z0-9\_\\-]+)', answer)
    saved = \[]

    for i, rid in enumerate(resource\_ids, 1):
        resp = requests.get(
            f"{files\_base}/files",             # ← 根路径，不是 /api/v1/files
            headers={"X-API-Key": api\_key},
            params={"file\_path": f"resource://{rid}"},
        )
        if resp.status\_code == 200:
            content\_type = resp.headers.get("Content-Type", "")
            ext = "jpg" if "jpeg" in content\_type else "png" if "png" in content\_type else "bin"
            path = f"{save\_dir}/image\_{i:02d}.{ext}"
            with open(path, "wb") as f:
                f.write(resp.content)
            saved.append(path)

    return saved
```

**前端 Blob 渲染（JavaScript）**：

```javascript
async function renderResourceImage(handle, filesBase, apiKey) {
    const resp = await fetch(
        `${filesBase}/files?file\_path=${encodeURIComponent('resource://' + handle)}`,
        { headers: { 'X-API-Key': apiKey } }
    );
    if (!resp.ok) return null;

    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);

    const img = document.createElement('img');
    img.src = blobUrl;
    img.onload = () => URL.revokeObjectURL(blobUrl); // 渲染后释放内存
    return img;
}
```

### Q10: `resource\_urls=public` 参数有什么用？如何启用？🆕

WeKnora v0.7.2 新增 `resource\_urls=public` query 参数，可让回答中的 `resource://` 句柄自动转换为可直接访问的 HTTP URL（格式为 `/r/:token`），省去第二次下载调用。

**使用条件（需同时满足）**：

1. API Key 无知识库限制
2. 服务器 `.env` 中配置了 `APP\_EXTERNAL\_URL`
3. 服务器 `.env` 中配置了 `RESOURCE\_URL\_MODE=public`（可选）

**调用方式**：

```python
resp = requests.post(
    f"{base\_url}/agent-chat/{session\_id}?resource\_urls=public",  # 作为 query 参数
    headers=headers,
    json={"query": query, "agent\_enabled": True, "agent\_id": agent\_id},
    stream=True,
)
# 回答中图片链接将变为 http://z2fpf345.tcp01.cn/r/xxxxx 格式
# 可直接作为 <img src> 使用
```

\---

## 10\. 错误码参考

|HTTP 状态码|说明|
|-|-|
|200|成功|
|400|请求参数错误|
|401|鉴权失败（API Key 无效）|
|403|权限不足；或使用知识库限制型 API Key 调用 `/files` 接口（需换用无限制 Key）🆕|
|404|资源不存在（知识库/知识/会话 ID 错误）|
|500|服务端内部错误|

\---

## 11\. 联系方式

如有对接问题，请联系 WeKnora 服务端管理员，提供以下信息：

1. 请求的完整 URL
2. 请求参数（脱敏）
3. 响应状态码和错误信息
