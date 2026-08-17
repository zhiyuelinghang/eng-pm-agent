# MCP 包上传与运行说明

平台现在直接管理依赖完整的 STDIO MCP 包，不需要额外部署 MCP 管理器，也不依赖 Docker。
管理端负责上传、启动检测和智能体分配；AgentScope 在真正对话时按会话启动并复用 MCP
进程，因此管理端会话和工程管理平台会话使用的是同一份配置与程序包。

**MCP 上传与开发语言无关，并非只支持 Python。** 平台本质上是按照 `mcp.json` 启动一个
可执行命令，只要程序实现标准 STDIO MCP 协议，就可以使用 Node.js、TypeScript、Python、
Go、Rust、Java 或其他语言。Node.js MCP 与 Python MCP 使用完全相同的上传、检测和分配
流程。

## 1. 支持范围与交付原则

- 当前“上传 MCP”管理的是 **STDIO MCP 完整运行包**，不是源码构建平台；
- 平台不会在上传时执行 `npm install`、`pnpm install`、`pip install`、源码编译或
  Playwright 浏览器下载；
- Node.js/TypeScript MCP 应提交可直接运行的 `dist` 构建产物，或者把 `tsx`、
  `node_modules` 等运行依赖完整打包；仅有 `package.json` 和锁文件不算完整安装包；
- Python MCP 同样必须携带便携 Python 和完整依赖；
- Go、Rust 等 MCP 应携带编译后的可执行文件；Java MCP 必须携带可运行 JRE；
- 所有运行时和依赖都必须在安装包内，禁止使用服务器 `PATH` 中的全局 `node`、`python`、
  `java`、`bash` 等命令，也禁止在服务器上现场安装依赖；
- 当前上传入口不注册 Streamable HTTP 地址。需要独立部署的 HTTP MCP 不应伪装成上传包。

需要浏览器、GPU、大模型权重或其他大型外部运行环境的 MCP，仍可由 Node.js 等语言实现，
但必须确认安装包满足 200 MB 上传、500 MB 解压上限，并且目标服务器具备对应运行条件。
超出这一交付边界时，更适合把 MCP 独立部署为服务，再通过专门的远程 MCP 注册能力接入。

## 2. 安装包结构

上传文件可以使用 `.zip`、`.mcp` 或 `.mcpb` 扩展名，三者内部均为 ZIP 格式。安装包中
必须且只能有一个 `mcp.json`，它所在的目录就是 MCP 的运行目录。

```text
node-project-mcp.zip
└─ node-project-mcp/
   ├─ mcp.json
   ├─ runtime/
   │  └─ node.exe
   ├─ dist/
   │  └─ server.js
   └─ node_modules/
      └─ ...运行时依赖；已完整打包进 dist 时可省略...
```

包可以再套一层目录；平台会自动找到 `mcp.json`。`command` 指向包内可执行文件时，路径
必须相对于 `mcp.json` 所在目录。Windows 和 Linux 的运行文件并不通用，上传包必须与
目标服务器操作系统匹配。

安装包里的 `mcp.json` 是本平台的**安装清单**，不是 Claude Desktop 等客户端使用的
`.mcp.json`/`mcpServers` 连接配置，也不是项目自定义的 `manifest.json`。安装包必须且
只能包含一个符合下述结构的 `mcp.json`。

## 3. mcp.json

### 3.1 Node.js 示例

```json
{
  "schema_version": 1,
  "name": "node-project-data",
  "display_name": "Node.js 项目数据查询",
  "version": "1.0.0",
  "description": "使用 Node.js 实现的标准 STDIO MCP。",
  "transport": "stdio",
  "command": "runtime/node.exe",
  "args": ["dist/server.js"],
  "env": {},
  "platform_capabilities": [],
  "startup_timeout": 30,
  "execution_timeout": 120
}
```

Node.js 安装包必须携带 `runtime/node.exe`（Windows）或 `runtime/node`（Linux）。不得把
`command` 写成裸命令 `node`，也不得依赖目标服务器的 Node 版本和 `PATH` 配置。

TypeScript 源码不能被 Node.js 直接执行。推荐先构建为 `dist/server.js`；如果选择用
`tsx` 直接运行 `.ts`，则必须把 `tsx` 及全部 `node_modules` 一并打包，并将 `command`
和 `args` 指向包内可用的实际入口。

### 3.2 Python 示例

```json
{
  "schema_version": 1,
  "name": "python-project-data",
  "display_name": "Python 项目数据查询",
  "version": "1.0.0",
  "description": "使用 Python 实现的标准 STDIO MCP。",
  "transport": "stdio",
  "command": "runtime/python.exe",
  "args": ["server.py"],
  "env": {
    "PYTHONPATH": "packages"
  },
  "platform_capabilities": [],
  "startup_timeout": 30,
  "execution_timeout": 120
}
```

字段说明：

- `name`：稳定技术标识，只能包含字母、数字、`-`、`_`，升级版本时不能修改；
- `display_name`：管理端显示名称；
- `version`：不可变版本号。同名同版本不能重复上传，提高版本号即可更新；
- `transport`：当前上传包固定为 `stdio`，与实现语言无关；
- `command`：安装包内的可执行文件路径；Python、Node.js、Java 等运行时必须随包携带，
  不允许填写服务器 `PATH` 中的裸命令；
- `args`：传给启动命令的参数；
- `env`：仅传给该 MCP 进程的固定环境变量，不会返回给浏览器；
- `platform_capabilities`：可选的平台托管能力声明。普通 MCP 保持空数组；受信业务包
  可以声明 `dobby_database_interactions`，获取受智能体分配、会话范围和表白名单控制的
  标准数据库交互接口；项目初始化智能体已直接使用平台数据库交互，不再依赖初始化 MCP；
- `startup_timeout`：上传检测和会话首次启动的超时秒数；
- `execution_timeout`：单次 MCP 工具调用的超时秒数。

MCP 必须使用标准输入输出传输协议。普通日志不能写入 stdout，否则会破坏 JSON-RPC
通信；日志应写入 stderr 或独立日志文件。

平台还会覆盖注入 `AGENTSCOPE_USER_ID`、`AGENTSCOPE_AGENT_ID` 和
`AGENTSCOPE_SESSION_ID`。项目数据类 MCP 必须根据会话反查当前用户和项目并重新校验成员
权限；不要让模型直接传入用户 ID 或项目 ID。声明 `dobby_database_interactions` 的包会获得
内部数据库交互地址和专用服务令牌。这些值只存在于 MCP 子进程环境中，不会进入浏览器
接口或上传包。

平台不向 MCP 注入数据库文件路径、数据库账号或原始 SQL 执行能力。受信业务 MCP 也只能
按已分配交互读取或修改当前会话范围内的记录；每次写入都会重新检查数据表白名单，并由平台
补充项目、会话、用户、执行智能体和审计信息。因此切换 SQLite 或其他数据库时无需重写 MCP。

## 4. 上传、升级与分配

1. 在智能体聊天页右侧切换到 `MCP`；
2. 点击“上传 MCP”并选择完整安装包；
3. 服务端解压到临时目录，直接按 `command + args` 启动 MCP 并调用 `tools/list`；
4. 只有启动成功的包才会进入平台目录；
5. 勾选要分配给当前智能体的 MCP，点击“保存分配”；
6. 下一次对话运行时自动装载；无需在工程管理平台重复配置。

更新时保持 `name` 不变并提高 `version`。已有智能体分配使用稳定的 `name`，因此更新后
不需要重新勾选；各会话在下次运行时切换到新版本。仍被任一智能体使用的 MCP 不允许
删除，应先取消分配。

上传阶段不会补装依赖。如果 Node.js 包缺少 `node_modules`、构建产物或所需浏览器，或者
Python 包缺少解释器和依赖，都会在第 3 步启动检测时失败，不会进入平台目录。

## 5. 并发与生命周期

- 程序包只保存一份，但运行进程按 `(会话 ID, MCP name)` 隔离；
- 同一会话连续多轮对话复用同一个 MCP 进程，可保留会话内状态；
- 不同平台用户、管理端会话和协同智能体会话不会共享 MCP 进程状态；
- 会话删除时立即关闭对应进程；空闲超过 3600 秒也会自动关闭；
- 默认最多同时运行 128 个 MCP 进程，可通过 `.env` 中的
  `AGENTSCOPE_MCP_MAX_ACTIVE_INSTANCES` 调整。

这里的并发上限是服务器保护阈值，不是 MCP 工具的业务并发能力。数据库连接池、第三方
接口限流等仍应由各 MCP 自身正确处理。

## 6. 安全边界

上传的 MCP 是服务器本地程序，运行权限与 AgentScope 服务进程相同。平台会阻止 ZIP
路径穿越、符号链接、超大解压和包外启动命令，但这不是代码沙箱。因此上传权限只应开放
给可信管理人员，安装包也必须来自可信开发者。

声明 `dobby_database_interactions` 的包仍属于受信业务包。平台负责会话、用户、项目、字段
白名单和并发版本校验；MCP 负责业务流程、参数模型与跨分区校验，双方都不能绕过用户最终
确认后才正式入库的边界。

初始化流程不限制附件数量，也不限制 MinerU 结果 ZIP 内的文件数量；附件和结构化记录按
页循环读取。为防止异常压缩包耗尽服务器资源，附件解析仍会校验解压后总大小，但该校验
与文件数量无关。
