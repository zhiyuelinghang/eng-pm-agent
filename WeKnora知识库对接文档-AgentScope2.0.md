# WeKnora 知识库对接文档

> 面向 AgentScope 2.0 开发人员的 WeKnora 知识管理服务集成指南

---

## 1. 概览

### 1.1 WeKnora 提供什么

WeKnora 是一个完整的知识管理平台，为 AgentScope 2.0 智能体提供以下能力：

| 能力 | 说明 |
|---|---|
| **文档管理** | 支持 PDF、Word、TXT、Markdown、HTML 等多种格式的知识入库 |
| **URL 抓取** | 从网页 URL 自动提取内容并入库 |
| **混合检索** | 向量检索 + 关键词检索，返回相关片段及溯源信息 |
| **RAG 对话** | 检索→重排→LLM 总结的完整流水线（SSE 流式返回） |
| **Agent 对话** | Agent 自主调用工具进行多步推理（SSE 流式返回） |
| **文件下载/预览** | 原始文件下载与在线预览 |
| **Wiki 生成** | 基于知识库自动生成结构化 Wiki 页面 |

### 1.2 服务地址与鉴权

| 配置项 | 值 |
|---|---|
| **Base URL** | `http://z2fpf345.tcp01.cn` |
| **API 前缀** | `/api/v1` |
| **API Key** | `<your-api-key>` |
| **鉴权方式** | 请求头 `X-API-Key: <your-api-key>` |
| **Content-Type** | `application/json`（文件上传为 `multipart/form-data`） |

> ⚠️ **安全提醒**：当前服务地址为 HTTP，API Key 会明文传输。**生产环境强烈建议升级为 HTTPS**。

### 1.3 核心概念说明

在对接前，请先区分以下三个概念——它们名称相近但用途完全不同：

| 概念 | 是什么 | 格式示例 | 用途 |
|---|---|---|---|
| **API Key** | 租户级别的**鉴权密钥**（类似密码） | `<your-api-key>` | 放在请求头 `X-API-Key` 中，**每个请求都要带**，用于身份验证 |
| **知识库 ID** (KB ID) | 某个知识库的**唯一标识** | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` | 在 URL 路径或请求体中传入，表示"操作哪个知识库" |
| **知识 ID** (Knowledge ID) | 某条知识（某个文件/URL/手动内容）的**唯一标识** | `kg-uuid-001` | 用于获取知识详情、下载文件、查看分块等 |

**获取方式**：
- **API Key**：在 WeKnora 管理界面 → 设置 → API 密钥中创建
- **知识库 ID**：调用 `GET /api/v1/knowledge-bases` 获取所有知识库列表，读取 `id` 字段
- **知识 ID**：调用 `GET /api/v1/knowledge-bases/:id/knowledge` 获取列表，或通过检索结果中的 `knowledge_id` 字段获得

**类比理解**：
- API Key = 进入大楼的门禁卡（身份验证）
- 知识库 ID = 你要去的具体楼层/房间号
- 知识 ID = 房间里的具体某个文件柜

### 1.4 鉴权示例

```python
import requests

BASE_URL = "http://z2fpf345.tcp01.cn/api/v1"
API_KEY = "<your-api-key>"

session = requests.Session()
session.headers.update({
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
})
```

---

## 2. 核心 API 一览

### 2.1 API 速查表

| 分类 | 方法 | 路径 | 用途 |
|---|---|---|---|
| **知识库** | GET | `/knowledge-bases` | 列出所有知识库 |
| | GET | `/knowledge-bases/:id` | 获取知识库详情 |
| | POST | `/knowledge-bases/:id/hybrid-search` | **混合检索（核心）** |
| **知识管理** | POST | `/knowledge-bases/:id/knowledge/file` | 上传文件创建知识 |
| | POST | `/knowledge-bases/:id/knowledge/url` | 从 URL 创建知识 |
| | GET | `/knowledge-bases/:id/knowledge` | 列出知识库中的知识 |
| | GET | `/knowledge/:id` | **获取知识详情（含文件信息）** |
| | GET | `/knowledge/batch?ids=id1,id2` | **批量获取知识详情** |
| | GET | `/knowledge/:id/download` | 下载原始文件 |
| | GET | `/knowledge/:id/preview` | 预览文件 |
| | DELETE | `/knowledge/:id` | 删除知识 |
| **分块管理** | GET | `/chunks/:knowledge_id` | 列出知识的文本分块 |
| **会话** | POST | `/sessions` | 创建对话会话 |
| | GET | `/sessions` | 列出会话 |
| **对话** | POST | `/knowledge-chat/:session_id` | RAG 对话（SSE 流式） |
| | POST | `/agent-chat/:session_id` | Agent 对话（SSE 流式） |
| **模型** | GET | `/models` | 列出所有模型 |
| **Agent** | GET | `/agents` | 列出所有自定义 Agent |
| | GET | `/agents/:id` | 获取 Agent 详情 |

---

## 3. 通用响应格式

所有 API 统一返回以下 JSON 结构：

```json
{
    "success": true,
    "data": { ... },      // 单个对象
    // 或
    "data": [ ... ],      // 列表
    "message": "ok"
}
```

分页列表格式：

```json
{
    "success": true,
    "data": {
        "list": [ ... ],
        "total": 100,
        "page": 1,
        "page_size": 20
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

---

## 4. 详细接口说明

### 4.1 知识库管理

#### 4.1.1 列出知识库（获取知识库 ID）

**对接第一步**：调用此接口获取当前租户下所有知识库的列表，从中取得 `id` 字段（即知识库 ID），后续所有操作（检索、上传、对话等）都需要用到它。

```
GET /api/v1/knowledge-bases
```

**curl 示例**：

```bash
curl -X GET "http://z2fpf345.tcp01.cn/api/v1/knowledge-bases" \
  -H "X-API-Key: <your-api-key>"
```

**Python 示例**：

```python
import requests

resp = requests.get(
    "http://z2fpf345.tcp01.cn/api/v1/knowledge-bases",
    headers={"X-API-Key": "<your-api-key>"},
)
kbs = resp.json().get("data", [])

for kb in kbs:
    print(f"ID: {kb['id']}, 名称: {kb['name']}, 描述: {kb.get('description', '')}")
```

**响应示例**：

```json
{
    "success": true,
    "data": [
        {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "name": "产品知识库",
            "description": "包含所有产品文档",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-06-01T00:00:00Z"
        },
        {
            "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
            "name": "FAQ 知识库",
            "description": "常见问题解答",
            "created_at": "2025-03-01T00:00:00Z",
            "updated_at": "2025-07-01T00:00:00Z"
        }
    ]
}
```

**响应字段说明**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | **知识库 ID**（UUID），后续所有接口都需要用到 |
| `name` | string | 知识库名称 |
| `description` | string | 知识库描述 |
| `created_at` | string | 创建时间 |
| `updated_at` | string | 最后更新时间 |

**如何使用返回的知识库 ID**：

拿到 `id` 后，将其作为后续接口中的 `:id` 或 `kb_id` 参数使用，例如：

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
    "query_text": "如何配置 VPN 连接？",
    "vector_threshold": 0.5,
    "keyword_threshold": 0.3,
    "match_count": 5
}
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `query_text` | string | ✅ | — | 检索文本 |
| `vector_threshold` | float | ❌ | 0.5 | 向量相似度阈值（0~1） |
| `keyword_threshold` | float | ❌ | 0.3 | 关键词匹配阈值（0~1） |
| `match_count` | int | ❌ | 5 | 返回结果数量 |

**响应示例**：

```json
{
    "success": true,
    "data": [
        {
            "id": "chunk-uuid-001",
            "content": "VPN 连接配置步骤：\n1. 打开设置 > 网络 > VPN\n2. 点击添加 VPN 配置...",
            "knowledge_id": "kg-uuid-001",
            "knowledge_title": "VPN 配置手册",
            "knowledge_filename": "vpn-guide.pdf",
            "knowledge_source": "",
            "knowledge_channel": "web",
            "chunk_index": 3,
            "start_at": 1200,
            "end_at": 1800,
            "score": 0.92,
            "match_type": "vector",
            "chunk_type": "text"
        },
        {
            "id": "chunk-uuid-002",
            "content": "VPN 常见问题排查...",
            "knowledge_id": "kg-uuid-002",
            "knowledge_title": "网络故障排查手册",
            "knowledge_filename": "troubleshoot.docx",
            "knowledge_source": "",
            "knowledge_channel": "api",
            "chunk_index": 7,
            "start_at": 3400,
            "end_at": 4100,
            "score": 0.78,
            "match_type": "hybrid",
            "chunk_type": "text"
        }
    ]
}
```

**搜索结果字段说明**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | Chunk ID |
| `content` | string | 匹配的文本片段内容 |
| `knowledge_id` | string | **知识条目 ID**（用于获取文件详情和下载） |
| `knowledge_title` | string | 知识标题 |
| `knowledge_filename` | string | **原始文件名** |
| `knowledge_source` | string | URL 来源（URL 类型知识有值） |
| `knowledge_channel` | string | 入库渠道（web/api/feishu/notion 等） |
| `chunk_index` | int | 分块在原文中的序号 |
| `start_at` | int | 片段在原文中的起始字符位置 |
| `end_at` | int | 片段在原文中的结束字符位置 |
| `score` | float | 相关度评分（越高越相关） |
| `match_type` | string | 匹配方式：`vector` / `keyword` / `hybrid` |
| `chunk_type` | string | 分块类型（text / image 等） |

---

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
        "knowledge_base_id": "kb-uuid-001",
        "type": "file",
        "title": "VPN 配置手册",
        "description": "",
        "file_name": "vpn-guide.pdf",
        "file_type": "pdf",
        "file_size": 2048000,
        "file_path": "local://1/abc123/vpn-guide.pdf",
        "file_hash": "sha256:e3b0c44298fc1c14...",
        "source": "",
        "channel": "web",
        "parse_status": "completed",
        "enable_status": "enabled",
        "created_at": "2025-06-01T00:00:00Z",
        "processed_at": "2025-06-01T00:05:00Z"
    }
}
```

**文件相关字段**：

| 字段 | 说明 |
|---|---|
| `file_name` | 原始文件名 |
| `file_type` | 文件类型（pdf / docx / md / txt / html 等） |
| `file_size` | 文件大小（bytes） |
| `file_path` | 存储路径（`provider://path` 格式） |
| `file_hash` | 文件哈希 |
| `source` | URL 来源（URL 入库时有值，文件入库时为空） |

#### 4.2.2 批量获取知识详情

当搜索结果涉及多个知识文件时，使用批量接口减少请求次数：

```
GET /api/v1/knowledge/batch?ids=kg-uuid-001,kg-uuid-002,kg-uuid-003
```

**响应**：同 `GetKnowledge`，`data` 为数组。

#### 4.2.3 列出知识库中的知识

```
GET /api/v1/knowledge-bases/:id/knowledge?page=1&page_size=20
```

支持筛选参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `page` | int | 页码，默认 1 |
| `page_size` | int | 每页数量，默认 20 |
| `keyword` | string | 按文件名/标题关键词筛选 |
| `file_type` | string | 按文件类型筛选 |
| `parse_status` | string | 按解析状态筛选（pending/processing/completed/failed） |
| `source` | string | 按来源渠道筛选（web/api/feishu/notion 等） |

#### 4.2.4 上传文件创建知识

```
POST /api/v1/knowledge-bases/:id/knowledge/file
Content-Type: multipart/form-data
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | ✅ | 上传的文件 |
| `enable_multimodel` | string | ❌ | 是否启用多模态处理（默认 `true`） |

#### 4.2.5 从 URL 创建知识

```
POST /api/v1/knowledge-bases/:id/knowledge/url
```

```json
{
    "url": "https://example.com/docs/guide.html",
    "enable_multimodel": true
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

---

### 4.3 对话功能

#### 4.3.1 创建会话

在对话前需要先创建一个绑定知识库的会话：

```
POST /api/v1/sessions
```

```json
{
    "knowledge_base_id": "kb-uuid-001",
    "title": "产品咨询",
    "description": "客户产品使用咨询",
    "session_strategy": {
        "max_rounds": 10,
        "enable_rewrite": true,
        "fallback_strategy": "FIXED_RESPONSE",
        "fallback_response": "抱歉，我暂时无法回答这个问题。",
        "embedding_top_k": 10,
        "keyword_threshold": 0.5,
        "vector_threshold": 0.7,
        "summary_model_id": ""
    }
}
```

**响应**：

```json
{
    "success": true,
    "data": {
        "id": "session-uuid-001",
        "knowledge_base_id": "kb-uuid-001",
        "title": "产品咨询",
        "created_at": "2025-08-10T00:00:00Z"
    }
}
```

#### 4.3.2 RAG 对话（知识问答）

```
POST /api/v1/knowledge-chat/:session_id
```

**请求**：

```json
{
    "query": "如何配置 VPN？",
    "knowledge_base_ids": ["kb-uuid-001"],
    "web_search_enabled": false,
    "enable_memory": false,
    "channel": "api"
}
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | ✅ | 用户问题 |
| `knowledge_base_ids` | string[] | ❌ | 知识库 ID 列表（强烈建议提供） |
| `web_search_enabled` | bool | ❌ | 是否启用联网搜索 |
| `enable_memory` | bool | ❌ | 是否启用跨会话记忆 |
| `channel` | string | ❌ | 渠道标识，建议传 `"api"` |

**响应**（SSE 流式）：

```
data: {"response_type": "answer", "content": "根据"}

data: {"response_type": "answer", "content": "文档，VPN"}

data: {"response_type": "answer", "content": "配置步骤如下..."}

data: {"response_type": "references", "knowledge_references": [
    {"id": "chunk-001", "content": "...", "knowledge_id": "kg-001", "knowledge_title": "VPN手册", "score": 0.92}
]}

data: {"response_type": "complete"}
```

| SSE 事件类型 | 说明 |
|---|---|
| `answer` | LLM 回答片段（增量），拼接所有 `content` 即为完整回答 |
| `references` | 引用的知识片段列表，结构与混合检索结果一致 |
| `error` | 错误信息 |
| `complete` | 对话完成标志 |

#### 4.3.3 Agent 对话（工具调用）

```
POST /api/v1/agent-chat/:session_id
```

```json
{
    "query": "对比 VPN 和 SSH 隧道的优缺点",
    "agent_id": "agent-uuid-001",
    "knowledge_base_ids": ["kb-uuid-001"],
    "channel": "api"
}
```

> Agent 会自主决定调用哪些工具（知识检索、联网搜索等），响应格式同 RAG 对话。

---

### 4.4 分块管理

#### 4.4.1 列出知识的文本分块

```
GET /api/v1/chunks/:knowledge_id?page=1&page_size=20
```

**响应**：

```json
{
    "success": true,
    "data": {
        "list": [
            {
                "id": "chunk-uuid-001",
                "knowledge_id": "kg-uuid-001",
                "content": "第一章 概述\n本文档介绍了...",
                "chunk_index": 0,
                "start_at": 0,
                "end_at": 500,
                "is_enabled": true,
                "created_at": "2025-06-01T00:05:00Z"
            }
        ],
        "total": 25,
        "page": 1,
        "page_size": 20
    }
}
```

---

## 5. AgentScope 2.0 集成方案

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
    base_url: str = "http://z2fpf345.tcp01.cn/api/v1"
    api_key: str = ""
    timeout: int = 30        # 普通请求超时（秒）
    chat_timeout: int = 300  # SSE 流式读取超时（秒）


@dataclass
class SearchReference:
    """检索引用"""
    knowledge_id: str
    title: str
    filename: str
    source: str              # URL 来源
    content: str             # 匹配的文本片段
    score: float             # 相关度
    chunk_index: int         # 原文中的分块序号
    start_at: int            # 起始字符位置
    end_at: int              # 结束字符位置
    match_type: str          # vector / keyword / hybrid
    # 文件元信息（通过 get_knowledge 补充）
    file_name: str = ""
    file_type: str = ""
    file_size: int = 0
    file_path: str = ""


class WeKnoraClient:
    """WeKnora REST API 客户端"""

    def __init__(self, config: WeKnoraConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": config.api_key,
            "Content-Type": "application/json",
        })

    def _get(self, path: str, params: dict = None) -> dict:
        resp = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict = None) -> dict:
        resp = self.session.post(
            f"{self.base_url}{path}",
            json=data or {},
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ── 知识库 ─────────────────────────────────────────────

    def list_knowledge_bases(self) -> list:
        """列出所有知识库"""
        result = self._get("/knowledge-bases")
        return result.get("data", [])

    # ── 检索 ───────────────────────────────────────────────

    def hybrid_search(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
        vector_threshold: float = 0.5,
        keyword_threshold: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """
        混合检索（核心方法）

        Args:
            kb_id: 知识库 ID
            query: 检索文本
            top_k: 返回结果数
            vector_threshold: 向量相似度阈值
            keyword_threshold: 关键词匹配阈值

        Returns:
            搜索结果列表，每条包含 knowledge_id, content, score 等
        """
        result = self._post(
            f"/knowledge-bases/{kb_id}/hybrid-search",
            data={
                "query_text": query,
                "vector_threshold": vector_threshold,
                "keyword_threshold": keyword_threshold,
                "match_count": top_k,
            },
        )
        return result.get("data", [])

    # ── 知识详情 ───────────────────────────────────────────

    def get_knowledge(self, knowledge_id: str) -> dict:
        """
        获取知识详情（含 file_path, file_name, source 等文件信息）

        用于在前端展示原始文件信息、提供下载/预览链接
        """
        result = self._get(f"/knowledge/{knowledge_id}")
        return result.get("data", {})

    def get_knowledge_batch(self, knowledge_ids: List[str]) -> list:
        """
        批量获取知识详情

        当搜索结果涉及多个知识文件时，一次性获取所有文件信息，
        减少请求次数。
        """
        if not knowledge_ids:
            return []
        result = self._get(
            "/knowledge/batch",
            params={"ids": ",".join(knowledge_ids)},
        )
        return result.get("data", [])

    # ── 文件操作 ───────────────────────────────────────────

    def download_file_url(self, knowledge_id: str) -> str:
        """获取原始文件下载 URL"""
        return f"{self.base_url}/knowledge/{knowledge_id}/download"

    def preview_file_url(self, knowledge_id: str) -> str:
        """获取文件预览 URL"""
        return f"{self.base_url}/knowledge/{knowledge_id}/preview"

    def download_file(self, knowledge_id: str) -> bytes:
        """下载原始文件内容"""
        resp = self.session.get(
            f"{self.base_url}/knowledge/{knowledge_id}/download",
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        return resp.content

    # ── 知识入库 ───────────────────────────────────────────

    def upload_file(self, kb_id: str, file_path: str, enable_multimodal: bool = True) -> dict:
        """
        上传文件到知识库

        Args:
            kb_id: 知识库 ID
            file_path: 本地文件路径
            enable_multimodal: 是否启用多模态处理
        """
        headers = {"X-API-Key": self.config.api_key}
        # 移除 Content-Type，让 requests 自动设置 multipart boundary
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"{self.base_url}/knowledge-bases/{kb_id}/knowledge/file",
                headers=headers,
                files={"file": f},
                data={"enable_multimodel": str(enable_multimodal).lower()},
                timeout=self.config.timeout,
            )
        resp.raise_for_status()
        return resp.json()

    def create_from_url(self, kb_id: str, url: str, enable_multimodal: bool = True) -> dict:
        """从 URL 创建知识"""
        return self._post(
            f"/knowledge-bases/{kb_id}/knowledge/url",
            data={"url": url, "enable_multimodel": enable_multimodal},
        )

    # ── 会话与对话 ─────────────────────────────────────────

    def create_session(
        self,
        kb_id: str,
        title: str = "",
        max_rounds: int = 10,
    ) -> str:
        """
        创建对话会话，返回 session_id
        """
        data = {
            "knowledge_base_id": kb_id,
            "session_strategy": {
                "max_rounds": max_rounds,
                "enable_rewrite": True,
                "fallback_strategy": "FIXED_RESPONSE",
                "fallback_response": "抱歉，我暂时无法回答这个问题。",
            },
        }
        if title:
            data["title"] = title
        result = self._post("/sessions", data=data)
        return result.get("data", {}).get("id", "")

    def chat_stream(self, session_id: str, query: str, kb_ids: List[str] = None):
        """
        RAG 对话（SSE 流式）

        Yields:
            dict: {"type": "answer"|"references"|"complete", "content": ...}
        """
        body = {"query": query, "channel": "api"}
        if kb_ids:
            body["knowledge_base_ids"] = kb_ids

        resp = self.session.post(
            f"{self.base_url}/knowledge-chat/{session_id}",
            json=body,
            stream=True,
            timeout=(10, self.config.chat_timeout),
        )
        resp.raise_for_status()

        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            if isinstance(raw_line, bytes):
                raw_line = raw_line.decode("utf-8")
            if not raw_line.startswith("data:"):
                continue
            payload = raw_line[5:].lstrip()
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue

            response_type = event.get("response_type", "")
            if response_type == "answer":
                yield {"type": "answer", "content": event.get("content", "")}
            elif response_type == "references":
                yield {"type": "references", "data": event.get("knowledge_references", [])}
            elif response_type == "complete":
                yield {"type": "complete"}
                break
            elif response_type == "error":
                yield {"type": "error", "content": event.get("content", "")}
                break


class WeKnoraKnowledgeTool:
    """
    AgentScope 2.0 Tool 封装

    将 WeKnora 封装为 Agent 可调用的 tool，
    返回检索结果 + 文件溯源信息供前端可视化。
    """

    def __init__(self, client: WeKnoraClient, default_kb_id: str = ""):
        self.client = client
        self.default_kb_id = default_kb_id

    def search(self, query: str, kb_id: str = "", top_k: int = 5) -> dict:
        """
        知识检索 tool

        供 AgentScope Agent 调用，返回检索片段和溯源信息。
        """
        target_kb = kb_id or self.default_kb_id
        if not target_kb:
            return {"error": "未指定知识库 ID"}

        # 1. 混合检索
        results = self.client.hybrid_search(target_kb, query, top_k=top_k)

        # 2. 批量获取文件元信息
        knowledge_ids = list({r.get("knowledge_id") for r in results if r.get("knowledge_id")})
        file_info_map = {}
        batch = self.client.get_knowledge_batch(knowledge_ids)
        for kg in batch:
            file_info_map[kg["id"]] = {
                "file_name": kg.get("file_name", ""),
                "file_type": kg.get("file_type", ""),
                "file_size": kg.get("file_size", 0),
                "file_path": kg.get("file_path", ""),
                "source": kg.get("source", ""),
                "title": kg.get("title", ""),
                "download_url": self.client.download_file_url(kg["id"]),
                "preview_url": self.client.preview_file_url(kg["id"]),
            }

        # 3. 组装返回
        return {
            "query": query,
            "total": len(results),
            "references": [
                {
                    "knowledge_id": r.get("knowledge_id", ""),
                    "title": r.get("knowledge_title", ""),
                    "filename": r.get("knowledge_filename", ""),
                    "content": r.get("content", ""),
                    "score": round(r.get("score", 0), 4),
                    "chunk_index": r.get("chunk_index", 0),
                    "start_at": r.get("start_at", 0),
                    "end_at": r.get("end_at", 0),
                    "match_type": r.get("match_type", ""),
                    "file_info": file_info_map.get(r.get("knowledge_id", ""), {}),
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
    base_url="http://z2fpf345.tcp01.cn/api/v1",
    api_key="<your-api-key>",
))

# 创建知识检索 tool
kb_tool = WeKnoraKnowledgeTool(client, default_kb_id="your-kb-id")


class RAGAgent(AgentBase):
    """带知识库检索的 Agent"""

    def __init__(self, name: str, model_config_name: str, **kwargs):
        super().__init__(name=name, model_config_name=model_config_name, **kwargs)

    def reply(self, x: Msg = None) -> Msg:
        query = x.content

        # ① 检索知识
        search_result = kb_tool.search(query, top_k=5)

        # ② 组装 prompt
        context_parts = []
        references_for_frontend = []

        for ref in search_result.get("references", []):
            context_parts.append(
                f"[来源: {ref['filename']}] (相关度: {ref['score']})\n"
                f"{ref['content']}"
            )
            references_for_frontend.append({
                "knowledge_id": ref["knowledge_id"],
                "title": ref["title"],
                "filename": ref["filename"],
                "score": ref["score"],
                "content_snippet": ref["content"][:200],
                "file_info": ref["file_info"],
            })

        context = "\n\n---\n\n".join(context_parts) if context_parts else "（未检索到相关知识）"

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
            metadata={"references": references_for_frontend},  # 引用溯源
        )
```

### 5.4 前端可视化数据结构

Agent 返回的 `references` 数组可直接用于前端知识库资料可视化：

```typescript
// 前端 TypeScript 类型定义
interface KnowledgeReference {
    knowledge_id: string;
    title: string;           // 知识标题
    filename: string;        // 原始文件名
    score: number;           // 相关度评分
    content_snippet: string; // 匹配的文本片段（前 200 字）
    file_info: {
        file_name: string;   // 文件名
        file_type: string;   // 文件类型（pdf/docx/md...）
        file_size: number;   // 文件大小（bytes）
        file_path: string;   // 存储路径
        source: string;      // URL 来源
        title: string;       // 知识标题
        download_url: string;// 下载链接（需后端代理）
        preview_url: string; // 预览链接（需后端代理）
    };
}
```

**前端可视化建议**：

| 可视化元素 | 实现方式 |
|---|---|
| 引用来源列表 | 显示 `filename` + `score` |
| 文件类型图标 | 根据 `file_type` 显示对应图标 |
| 文本片段预览 | 显示 `content_snippet`，高亮关键词 |
| 原始文件下载 | 调后端代理接口转发 `download_url` |
| 文件在线预览 | 后端代理转发 `preview_url` |
| URL 来源跳转 | 当 `source` 非空时显示外链图标 |
| 相关度排序 | 按 `score` 降序排列 |

---

## 6. 文件路径披露（知识库资料可视化）

AgentScope 前端需要展示知识库中的文件信息（文件名、大小、类型、来源等），甚至提供原始文件下载。本节说明如何从 WeKnora 获取这些文件元信息。

### 6.1 数据流转概览

```
┌────────────────────────────────────────────────────────────────────────┐
│  AgentScope 前端                                                       │
│                                                                        │
│  用户看到：                                                            │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ 📄 vpn-guide.pdf    (2.0 MB)   相关度: 0.92     [下载] [预览]  │  │
│  │ 📄 troubleshoot.docx (800 KB)   相关度: 0.78     [下载] [预览]  │  │
│  │ 🌐 https://example.com/guide                                    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                     ▲                                                  │
│                     │ 展示 file_name, file_type, file_size, source     │
│                     │                                                  │
│  AgentScope 后端    │                                                  │
│  ┌──────────────┐   │                                                  │
│  │ 1. 调 hybrid-search → 拿到 knowledge_id                            │
│  │ 2. 调 GET /knowledge/batch?ids=... → 拿到文件元信息                 │
│  │ 3. 组装 references 返回给前端                                       │
│  └──────────────┘                                                      │
└────────────────────────────────────────────────────────────────────────┘
```

### 6.2 第一步：从检索结果获取 knowledge_id

调用混合检索接口后，每条结果都包含 `knowledge_id`：

```python
results = client.hybrid_search(kb_id="your-kb-id", query="如何配置 VPN？", top_k=5)

# 提取所有 knowledge_id（去重）
knowledge_ids = list(set(r["knowledge_id"] for r in results))
# 示例输出: ["kg-uuid-001", "kg-uuid-002"]
```

### 6.3 第二步：批量获取文件元信息

通过 `GET /api/v1/knowledge/batch` 一次性获取所有文件详情：

```python
# 批量获取文件元信息
resp = session.get(
    f"{BASE_URL}/knowledge/batch",
    params={"ids": ",".join(knowledge_ids)},
)
knowledge_list = resp.json().get("data", [])
```

**每条知识返回的文件相关字段**：

```json
{
    "id": "kg-uuid-001",
    "title": "VPN 配置手册",
    "file_name": "vpn-guide.pdf",
    "file_type": "pdf",
    "file_size": 2097152,
    "file_path": "local://1/abc123/vpn-guide.pdf",
    "file_hash": "sha256:e3b0c44298fc1c14...",
    "source": "",
    "type": "file",
    "channel": "web",
    "parse_status": "completed"
}
```

**文件相关字段详解**：

| 字段 | 类型 | 说明 | 前端用途 |
|---|---|---|---|
| `file_name` | string | 原始文件名（含扩展名） | 展示文件名 |
| `file_type` | string | 文件类型（pdf / docx / md / txt / html / csv / xlsx 等） | 显示文件类型图标 |
| `file_size` | int | 文件大小（字节） | 展示文件大小（需转换 KB/MB） |
| `file_path` | string | 存储路径（`provider://path` 格式） | 内部标识，一般不直接暴露给前端 |
| `file_hash` | string | 文件内容哈希（SHA-256） | 去重校验 |
| `source` | string | URL 来源。文件上传时为空字符串；URL 抓取时为原始 URL | URL 类型知识展示来源链接 |
| `type` | string | 知识类型：`file` / `url` / `manual` | 区分知识来源类型 |
| `channel` | string | 入库渠道：`web` / `api` / `feishu` / `notion` 等 | 展示入库来源 |
| `parse_status` | string | 解析状态：`pending` / `processing` / `completed` / `failed` | 展示处理状态 |

### 6.4 第三步：组装前端可视化数据

```python
def build_visualization_data(search_results, knowledge_list):
    """将检索结果和文件元信息组装为前端可直接使用的结构"""

    # 建立 knowledge_id → 文件元信息 的映射
    kg_map = {kg["id"]: kg for kg in knowledge_list}

    references = []
    for r in search_results:
        kg_id = r.get("knowledge_id", "")
        kg_info = kg_map.get(kg_id, {})

        references.append({
            # ── 检索片段信息 ──
            "knowledge_id": kg_id,
            "title": r.get("knowledge_title", ""),
            "content_snippet": r.get("content", "")[:200],
            "score": r.get("score", 0),
            "chunk_index": r.get("chunk_index", 0),
            "match_type": r.get("match_type", ""),

            # ── 文件元信息（前端展示用）──
            "file_name": kg_info.get("file_name", ""),
            "file_type": kg_info.get("file_type", ""),
            "file_size": kg_info.get("file_size", 0),
            "file_path": kg_info.get("file_path", ""),
            "source": kg_info.get("source", ""),
            "knowledge_type": kg_info.get("type", ""),  # file / url / manual
            "parse_status": kg_info.get("parse_status", ""),

            # ── 操作链接（需后端代理，见第 8 节）──
            "download_url": f"/api/files/download/{kg_id}",
            "preview_url": f"/api/files/preview/{kg_id}",
        })

    return references
```

### 6.5 前端展示示例

```typescript
// 文件大小格式化
function formatFileSize(bytes: number): string {
    if (bytes === 0) return "—";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

// 根据 file_type 返回图标
function getFileIcon(fileType: string): string {
    const iconMap: Record<string, string> = {
        pdf: "📕",
        docx: "📘", doc: "📘",
        xlsx: "📗", xls: "📗", csv: "📗",
        pptx: "📙", ppt: "📙",
        md: "📝", txt: "📄",
        html: "🌐",
    };
    return iconMap[fileType] || "📄";
}

// 根据 knowledge_type 和 source 决定展示内容
function renderReference(ref: KnowledgeReference) {
    if (ref.knowledge_type === "url" && ref.source) {
        // URL 类型：展示来源链接
        return `<a href="${ref.source}" target="_blank">${ref.source}</a>`;
    }
    // 文件类型：展示文件名 + 大小
    return `${getFileIcon(ref.file_type)} ${ref.file_name} (${formatFileSize(ref.file_size)})`;
}
```

### 6.6 单个知识详情查询

如果只需要查某个知识的文件信息：

```
GET /api/v1/knowledge/:id
```

```python
# 获取单个知识的完整信息
resp = session.get(f"{BASE_URL}/knowledge/{knowledge_id}")
knowledge = resp.json().get("data", {})

print(f"文件名: {knowledge['file_name']}")
print(f"类型: {knowledge['file_type']}")
print(f"大小: {knowledge['file_size']} bytes")
print(f"存储路径: {knowledge['file_path']}")
print(f"来源: {knowledge['source']}")
```

---

## 7. 文件上传与解析

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
- WeKnora 的文件上传是**异步解析**的：上传成功后立即返回 `knowledge_id`，后台异步进行文档解析→分块→向量化
- 解析状态通过 `parse_status` 字段跟踪：`pending` → `processing` → `finalizing` → `completed`（或 `failed`）
- 只有 `parse_status = "completed"` 的知识才能被检索到

### 7.2 上传接口

```
POST /api/v1/knowledge-bases/:id/knowledge/file
Content-Type: multipart/form-data
```

**请求参数（form-data）**：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | File | ✅ | 上传的文件（最大 50MB，可通过 `MAX_FILE_SIZE_MB` 环境变量调整） |
| `enable_multimodel` | string | ❌ | 是否启用多模态处理（图片 OCR 等），默认 `"true"` |
| `fileName` | string | ❌ | 自定义文件名（可选，用于保留文件夹路径结构） |
| `metadata` | string | ❌ | JSON 字符串格式的自定义元数据（可选） |
| `tag_ids` | string | ❌ | 逗号分隔的标签 ID（可选，用于知识分类） |
| `channel` | string | ❌ | 入库渠道标识，建议传 `"api"` |
| `process_config` | string | ❌ | JSON 字符串，覆盖默认解析配置（可选） |

**支持的文件格式**：PDF、DOCX、DOC、TXT、Markdown、HTML、CSV、XLSX、PPTX 等常见文档格式。

### 7.3 响应格式

上传成功返回 HTTP 200：

```json
{
    "success": true,
    "data": {
        "id": "kg-new-uuid-001",
        "knowledge_base_id": "kb-uuid-001",
        "title": "新上传的产品手册.pdf",
        "file_name": "新上传的产品手册.pdf",
        "file_type": "pdf",
        "file_size": 1536000,
        "file_path": "local://1/def456/新上传的产品手册.pdf",
        "parse_status": "pending",
        "created_at": "2025-08-10T10:00:00Z"
    }
}
```

> 注意：上传成功后 `parse_status` 为 `"pending"`，表示正在等待后台解析。

### 7.4 完整上传代码示例

#### 方式一：AgentScope 后端直接代理（推荐）

由于 WeKnora 不直接面向终端用户，AgentScope 后端需要作为代理转发文件上传：

```python
from fastapi import FastAPI, UploadFile, File, Form
import requests

app = FastAPI()

WEKNORA_BASE_URL = "http://z2fpf345.tcp01.cn/api/v1"
WEKNORA_API_KEY = "<your-api-key>"


@app.post("/api/knowledge/upload")
async def upload_to_weknora(
    kb_id: str = Form(...),               # 目标知识库 ID
    file: UploadFile = File(...),          # 用户上传的文件
    enable_multimodel: bool = Form(True),  # 是否启用多模态
):
    """
    代理文件上传到 WeKnora

    前端 (用户浏览器) → AgentScope 后端 → WeKnora
    """
    # 读取文件内容
    file_content = await file.read()

    # 构造 multipart/form-data 请求转发到 WeKnora
    resp = requests.post(
        f"{WEKNORA_BASE_URL}/knowledge-bases/{kb_id}/knowledge/file",
        headers={"X-API-Key": WEKNORA_API_KEY},
        files={"file": (file.filename, file_content, file.content_type)},
        data={
            "enable_multimodel": str(enable_multimodel).lower(),
            "channel": "api",  # 标记来源渠道
        },
        timeout=120,
    )
    resp.raise_for_status()
    result = resp.json()

    return {
        "success": True,
        "knowledge_id": result.get("data", {}).get("id", ""),
        "file_name": result.get("data", {}).get("file_name", ""),
        "parse_status": result.get("data", {}).get("parse_status", ""),
        "message": "文件上传成功，正在后台解析中...",
    }
```

#### 方式二：Python SDK 直接调用

```python
def upload_file_to_weknora(
    kb_id: str,
    file_path: str,
    enable_multimodel: bool = True,
    custom_filename: str = "",
) -> dict:
    """
    上传本地文件到 WeKnora 知识库

    Args:
        kb_id: 知识库 ID
        file_path: 本地文件路径
        enable_multimodel: 是否启用多模态（图片 OCR 等）
        custom_filename: 自定义文件名（可选）

    Returns:
        创建的知识条目信息，包含 knowledge_id 和 parse_status
    """
    headers = {"X-API-Key": API_KEY}

    with open(file_path, "rb") as f:
        files = {"file": f}
        data = {
            "enable_multimodel": str(enable_multimodel).lower(),
            "channel": "api",
        }
        if custom_filename:
            data["fileName"] = custom_filename

        resp = requests.post(
            f"{BASE_URL}/knowledge-bases/{kb_id}/knowledge/file",
            headers=headers,
            files=files,
            data=data,
            timeout=120,
        )

    resp.raise_for_status()
    result = resp.json()

    if not result.get("success"):
        raise Exception(f"上传失败: {result.get('message', '未知错误')}")

    knowledge = result.get("data", {})
    return {
        "knowledge_id": knowledge.get("id"),
        "file_name": knowledge.get("file_name"),
        "file_size": knowledge.get("file_size"),
        "parse_status": knowledge.get("parse_status"),  # pending
    }
```

### 7.5 跟踪解析状态

上传后需要轮询解析状态，直到文件处理完成：

```python
import time

def wait_for_parse_complete(knowledge_id: str, timeout_seconds: int = 300) -> dict:
    """
    轮询等待知识解析完成

    Args:
        knowledge_id: 知识 ID
        timeout_seconds: 最大等待时间（秒）

    Returns:
        最终的知识详情（parse_status = completed 或 failed）
    """
    start_time = time.time()
    poll_interval = 3  # 每 3 秒轮询一次

    while time.time() - start_time < timeout_seconds:
        resp = session.get(f"{BASE_URL}/knowledge/{knowledge_id}")
        knowledge = resp.json().get("data", {})
        status = knowledge.get("parse_status", "")

        if status == "completed":
            print(f"✅ 解析完成: {knowledge.get('file_name')}")
            return knowledge
        elif status == "failed":
            error_msg = knowledge.get("error_message", "未知错误")
            raise Exception(f"❌ 解析失败: {error_msg}")
        elif status in ("pending", "processing", "finalizing"):
            print(f"⏳ 解析中... 当前状态: {status}")
            time.sleep(poll_interval)
        else:
            print(f"⚠️ 未知状态: {status}")
            time.sleep(poll_interval)

    raise TimeoutError(f"解析超时（{timeout_seconds}秒）")
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
    "enable_multimodel": true,
    "file_name": "产品指南",
    "title": "产品使用指南",
    "tag_ids": ["tag-uuid-001"],
    "channel": "api"
}
```

```python
def create_knowledge_from_url(kb_id: str, url: str, title: str = "") -> dict:
    """从 URL 创建知识"""
    data = {
        "url": url,
        "enable_multimodel": True,
        "channel": "api",
    }
    if title:
        data["title"] = title

    resp = session.post(f"{BASE_URL}/knowledge-bases/{kb_id}/knowledge/url", json=data)
    resp.raise_for_status()
    result = resp.json()

    return {
        "knowledge_id": result.get("data", {}).get("id"),
        "title": result.get("data", {}).get("title"),
        "parse_status": result.get("data", {}).get("parse_status"),
    }
```

### 7.7 完整流程示例：上传 → 等待 → 检索

```python
def full_upload_and_search_workflow(kb_id: str, file_path: str, query: str):
    """
    完整流程演示：上传文件 → 等待解析 → 检索内容
    """
    # ① 上传文件
    print("📤 上传文件...")
    upload_result = upload_file_to_weknora(kb_id, file_path)
    knowledge_id = upload_result["knowledge_id"]
    print(f"   知识 ID: {knowledge_id}")
    print(f"   解析状态: {upload_result['parse_status']}")

    # ② 等待解析完成
    print("\n⏳ 等待解析...")
    knowledge = wait_for_parse_complete(knowledge_id)
    print(f"   ✅ 解析完成！文件名: {knowledge['file_name']}")
    print(f"   文件大小: {knowledge['file_size']} bytes")
    print(f"   存储路径: {knowledge['file_path']}")

    # ③ 检索内容
    print(f"\n🔍 检索: {query}")
    results = client.hybrid_search(kb_id, query, top_k=3)

    for r in results:
        print(f"\n   📄 {r['knowledge_filename']} (相关度: {r['score']:.2f})")
        print(f"   片段: {r['content'][:100]}...")

    return results
```

### 7.8 上传常见问题

| 问题 | 原因与解决 |
|---|---|
| `文件大小不能超过50MB` | 默认限制 50MB。如需调大，需修改 WeKnora 服务器 `MAX_FILE_SIZE_MB` 环境变量并重启 |
| `File upload failed` | 请求格式不是 `multipart/form-data`，或 `file` 字段名写错 |
| 上传成功但检索不到 | 文件还在解析中，检查 `parse_status` 是否为 `completed` |
| `Unauthorized` | API Key 无效或没有该知识库的写入权限 |
| URL 抓取失败 | URL 不可访问，或被 WeKnora 的 SSRF 安全策略拦截 |

---

## 8. 文件下载代理

由于 WeKnora 不直接面向终端用户，**前端下载/预览文件需要在 AgentScope 后端加代理接口**：

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.get("/api/files/download/{knowledge_id}")
async def proxy_download(knowledge_id: str):
    """代理 WeKnora 文件下载"""
    resp = requests.get(
        client.download_file_url(knowledge_id),
        headers={"X-API-Key": client.config.api_key},
        stream=True,
    )
    resp.raise_for_status()
    return StreamingResponse(
        resp.iter_content(chunk_size=8192),
        media_type=resp.headers.get("Content-Type", "application/octet-stream"),
    )

@app.get("/api/files/preview/{knowledge_id}")
async def proxy_preview(knowledge_id: str):
    """代理 WeKnora 文件预览"""
    resp = requests.get(
        client.preview_file_url(knowledge_id),
        headers={"X-API-Key": client.config.api_key},
    )
    resp.raise_for_status()
    return resp.json()
```

---

## 9. 常见问题

### Q1: 如何获取 API Key？

登录 WeKnora 管理界面 → 设置 → API 密钥 → 创建新的 API Key。

请在 WeKnora 管理界面创建并使用独立的 API Key，勿将真实密钥写入代码或版本库。

> ⚠️ 注意：API Key 是**租户级别的鉴权密钥**，不是知识库 ID。知识库 ID 需要通过 `GET /api/v1/knowledge-bases` 接口获取。详见 [1.3 核心概念说明](#13-核心概念说明)。

### Q2: 知识库 ID 怎么获取？

调用 `GET /api/v1/knowledge-bases` 获取所有知识库列表，从中找到 `id` 字段。

### Q3: 搜索结果中的 knowledge_id 和 knowledge_filename 有什么区别？

- `knowledge_id`：知识条目的唯一标识（UUID），用于调 API 获取详情、下载文件等
- `knowledge_filename`：原始文件名（如 `vpn-guide.pdf`），仅用于展示

### Q4: 如何判断一个知识是文件上传的还是 URL 抓取的？

查看 `Knowledge.source` 字段：
- 为空字符串 `""`：文件上传
- 有 URL 值：从 URL 抓取
- 值为 `"manual"`：手动创建的 Markdown 知识

### Q5: RAG 对话和混合检索的区别？

| | 混合检索 | RAG 对话 |
|---|---|---|
| 返回内容 | 原始文本片段 | LLM 总结后的回答 + 引用 |
| 是否需要会话 | ❌ 不需要 | ✅ 需要 session_id |
| 是否消耗 LLM | ❌ | ✅ |
| 适用场景 | Agent 自行组装 prompt | 直接获取答案 |
| 推荐用法 | ⭐ AgentScope 推荐 | 快速原型验证 |

**AgentScope 推荐使用混合检索**：Agent 拿到检索片段后自行组装 prompt 调用 LLM，这样对推理流程有完全的控制权。

### Q6: SSE 流式对话如何解析？

```python
for chunk in client.chat_stream(session_id, query, kb_ids=["kb-id"]):
    if chunk["type"] == "answer":
        # 增量文本片段，拼接后展示
        print(chunk["content"], end="", flush=True)
    elif chunk["type"] == "references":
        # 引用列表，用于前端展示来源
        refs = chunk["data"]
    elif chunk["type"] == "complete":
        # 对话结束
        break
```

### Q7: 文件上传有什么限制？

通过 WeKnora 管理界面查看具体限制。常见支持格式：PDF、DOCX、TXT、MD、HTML、CSV、XLSX 等。

---

## 10. 错误码参考

| HTTP 状态码 | 说明 |
|---|---|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 鉴权失败（API Key 无效） |
| 403 | 权限不足 |
| 404 | 资源不存在（知识库/知识/会话 ID 错误） |
| 500 | 服务端内部错误 |

---

## 11. 联系方式

如有对接问题，请联系 WeKnora 服务端管理员，提供以下信息：
1. 请求的完整 URL
2. 请求参数（脱敏）
3. 响应状态码和错误信息
