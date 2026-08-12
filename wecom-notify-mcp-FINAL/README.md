\# wecom-notify-mcp



企业微信群机器人通知推送 MCP Server，为 Dobby 工程管理智能体提供消息推送能力。



\## 模块简介



本 MCP Server 将企业微信群机器人的消息发送能力封装为标准化工具，支持文本、Markdown、图片和图文消息四种推送类型。所有工具遵循统一返回信封结构，可被 Dobby Agent 或其他 MCP 客户端发现和调用。



\## 功能概览



| 工具名 | 功能 | 消息类型 |

|--------|------|----------|

| `wecom\\\_send\\\_text` | 发送纯文本通知，支持 @成员 | text |

| `wecom\\\_send\\\_markdown` | 发送可排版的 Markdown 格式消息 | markdown |

| `wecom\\\_send\\\_image` | 发送图片（本地路径或 base64），含 MD5 校验 | image |

| `wecom\\\_send\\\_news` | 发送图文消息（1\~8 条），含标题、描述、链接、缩略图 | news |

| `wecom\\\_get\\\_status` | 查询会话发送统计与错误记录（只读） | — |



\## 项目结构

wecom-notify-mcp/

├── manifest.json # MCP 元数据

├── requirements.txt

├── .env.example # 环境变量模板（不含真实 key）

├── README.md

├── src/

│ ├── server.py # MCP 协议入口

│ ├── tools/ # 工具层

│ │ ├── send\_text.py

│ │ ├── send\_markdown.py

│ │ ├── send\_image.py

│ │ ├── send\_news.py

│ │ └── get\_status.py

│ ├── session/ # 会话层

│ │ └── store.py

│ ├── validation/ # 校验层

│ │ └── message\_validator.py

│ ├── engine/ # 引擎层（纯计算）

│ │ └── webhook\_sender.py

│ └── schemas/ # 统一返回结构

│ └── envelope.py

├── prompts/

│ └── start\_guide.md

├── tests/

│ └── local.py # 本地测试脚本

├── gui.py # 本地 GUI 调试器（可选）

└── docs/

└── screenshots/ # 联调截图






## 架构设计

遵循《交互式 MCP Server 开发规范手册》四层架构：

| 层 | 职责 | 依赖方向 |
|----|------|----------|
| 工具层 `tools/` | 前置校验 → 调引擎 → 更新会话 → 组织返回信封 | 向下依赖 |
| 会话层 `session/` | 维护发送计数与错误记录 | — |
| 校验层 `validation/` | 消息内容长度、图片大小、图文格式校验 | — |
| 引擎层 `engine/` | 纯 HTTP 请求发送逻辑，可独立测试 | 不依赖上层 |

依赖方向严格单向：`tools → session/validation → engine`，引擎层不感知“用户”概念。

## 统一返回信封

所有工具返回均遵循以下结构：

```json
{
  "status": "ok | needs_input | running | error",
  "session_id": "wecom_xxxxxxxx",
  "state": "ACTIVE",
  "data": { ... },
  "message": "人类可读说明",
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述",
    "recoverable": true,
    "suggestion": "修正建议"
  }
}

快速开始

前置条件

Python 3.10+



企业微信测试群 + 群机器人 Webhook 地址



1\\. 获取 Webhook 地址

在企业微信群聊中：



点击右上角 ... → 群机器人（新版称“消息推送”）



添加机器人，复制 Webhook 地址



2\\. 安装依赖

bash

cd wecom-notify-mcp

pip install -r requirements.txt

3\\. 配置环境变量

bash

cp .env.example .env

编辑 .env，填入真实的 Webhook URL：



text

WECOM\\\_WEBHOOK\\\_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key

4\\. 本地测试

bash

python local.py

会在终端依次打印文本、Markdown、图片、状态查询的调用结果，并在测试群中收到对应消息。



5\\. 启动 GUI 调试器（可选）

bash

python gui.py

支持两大模式：



Markdown + 图片：编辑 Markdown 内容，选择图片，可复选同时发送



新闻图文：动态添加 1\\\~8 条图文条目，支持标题、描述、链接、缩略图



6\\. MCP Inspector 联调

bash

npx @modelcontextprotocol/inspector

配置：



Transport Type: Standard Input/Output (stdio)



Command: python



Args: src/server.py 的绝对路径



连接后在 Tools 面板中可看到 5 个工具，逐个调用验证。



状态机

text

ACTIVE ──→ (始终活跃，无状态迁移)





\\### 已知限制



| 限制项 | 说明 | 后续方案 |

| :--- | :--- | :--- |

| 仅支持群聊 | 群机器人无法私聊通知 | 自建应用方案 |

| 无交互回调 | 用户无法在消息内点击按钮反馈 | 自建应用 + 回调域名 |

| 缩略图需公网 URL | `wecom\\\_send\\\_news` 的 `picurl` 不支持本地文件 | 对接 MinIO 对象存储 |

| 文件/压缩包不能直发 | 群机器人无 `file` 类型 | 用链接替代，文件存 MinIO |



\\---



\\### 错误码速查



| errcode | 含义 | 处理 |

| :--- | :--- | :--- |

| `60020` | IP 不在白名单 | 管理后台配置可信 IP |

| `93000` | Webhook key 无效 | 检查 `.env` 中的 URL |

| `45009` | 频率超限 | 等待后重试（每分钟上限 20 条） |

| `301019` | 图片 MD5 不匹配 | 已由引擎层自动计算 MD5 |





版本

v0.1.0 — 5 个标准化工具，Inspector 联调通过



作者

陈加恩 — Dobby 工程管理智能体团队


