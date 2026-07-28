# 工程管理智能体

## 本地启动

在项目根目录运行：

```powershell
.\start_agentscope.bat
.\start-frontend.bat
```

第一个脚本启动 Dobby 智能体管理与执行服务；第二个脚本在 `38430`
端口启动平台后端 API，并在 `38429` 端口启动平台前端。两个服务都启动后，
平台全局主智能体才能读取或操作 Dobby 项目数据。启动顺序不影响权限边界，
但本地开发建议先启动 AgentScope，便于平台创建会话时立即完成健康检查。

## Python 运行环境约定（重要）

本项目默认不使用系统 `python`、`py`、Anaconda `base` 或其他 Conda 环境运行后端。

`start-frontend.bat` 已固定使用项目自带的便携 Python：

```text
<项目根目录>\python-3.13.14\python.exe
```

因此，后端启动、依赖核验和本地调试应优先使用这个解释器。不得根据系统 Python 或 Conda `base` 中缺少某个包，就判断项目运行环境缺少依赖。

只有在明确调整启动方案时，才改用 Conda 环境；届时必须同步修改启动脚本和本文档。若便携运行时目录缺失，应先恢复该目录，不要静默回退到其他 Python 环境。

## 目录说明

- `frontend`：Vue 3 + TypeScript 前端。
- `backend`：FastAPI 后端。
- `python-3.13.14`：项目默认便携 Python 运行时及已安装依赖。
- `AgentScope`：AgentScope 2.x 核心与管理 Web UI。
- `doc`：MVP 需求、架构、接口和开发排期资料。
- `原型`：产品原型和智能体架构方案。
- `会议纪要`：项目评审与决策记录。

## AgentScope 平台接入

AgentScope Web UI 是智能体管理端，工程管理平台是业务使用端：

- AgentScope 使用独立管理账号登录，该账号只作为进入管理页的凭证，与工程管理平台账号无关。
- 凭证、模型、智能体、知识库、MCP、权限策略等所有 AgentScope 配置对整个平台全局生效。
- 工程管理平台账号禁止登录 AgentScope；平台后端使用独立服务令牌调用 AgentScope。
- 在 AgentScope 的智能体配置中，将一个智能体设为“平台全局主智能体”。
- 将专项智能体设为“业务智能体”，并启用、发布；它们会动态显示在平台“业务工具”页面。
- 普通“问问 Dobby”对话进入全局主智能体，业务工具对话直接进入对应专项智能体。
- 全局主智能体可动态邀请所有已启用且允许协同的非主智能体；“发布”只控制业务工具页面是否展示。
- 平台后端负责用户、项目权限校验，并将受限的项目数据摘要注入当前对话；浏览器不会直接访问 AgentScope API。
- 平台会话会按需挂载 `dobby_*` 语义工具。工具只携带 AgentScope 会话 ID，
  平台后端再从数据库反查真实账号与项目，并在每次调用时重新校验成员状态；
  模型不能传入或伪造用户 ID、项目 ID。
- 专项智能体会话只获得只读平台工具；普通对话使用的全局主智能体可获得项目
  写工具。新增风险源、更新 WBS 进度等管理操作还会再次校验当前平台账号的
  管理员权限。所有成功写入都会记录操作审计。
- 工具网关只暴露任务、WBS、风险、资料、项目变更等受控业务动作，不提供
  任意 SQL、任意 API、账号权限、AgentScope 凭证或系统配置修改能力。

AgentScope 管理员登录时不需要填写服务器地址。开发环境由 Web UI 将
同源路径 `/agentscope-api` 自动代理到本机 AgentScope API；外网部署时
由 Nginx/网关转发该路径即可。如需覆盖，可在构建时设置
`VITE_AGENTSCOPE_API_BASE_URL`，内部地址不会交给登录用户配置。

默认连接配置位于 `.env.example`：

```text
AGENTSCOPE_BASE_URL=http://127.0.0.1:18642
AGENTSCOPE_ADMIN_USERNAME=请设置独立的管理账号
AGENTSCOPE_ADMIN_PASSWORD=请设置高强度管理密码
AGENTSCOPE_AUTH_SECRET=请替换为至少32位随机签名密钥
AGENTSCOPE_SERVICE_TOKEN=请替换为至少32位随机平台服务令牌
# 可选：单独设置 AgentScope -> Dobby 工具网关令牌；留空时复用平台服务令牌
DOBBY_AGENT_TOOL_TOKEN=
AGENTSCOPE_GLOBAL_CONFIG_ID=default
AGENTSCOPE_REQUEST_TIMEOUT_SECONDS=150
AGENTSCOPE_POLL_INTERVAL_SECONDS=0.35
```

平台 SQLite 按平台账号保存会话映射与消息审计；AgentScope SQLite 保存全局配置和执行会话。平台浏览器只能访问平台 API，平台后端会先校验账号与项目权限，再使用服务令牌访问对应的 AgentScope 会话。
