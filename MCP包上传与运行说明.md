# MCP 包上传与运行说明

平台现在直接管理依赖完整的 STDIO MCP 包，不需要额外部署 MCP 管理器，也不依赖 Docker。
管理端负责上传、启动检测和智能体分配；AgentScope 在真正对话时按会话启动并复用 MCP
进程，因此管理端会话和工程管理平台会话使用的是同一份配置与程序包。

## 1. 安装包结构

上传文件可以使用 `.zip`、`.mcp` 或 `.mcpb` 扩展名，三者内部均为 ZIP 格式。安装包中
必须且只能有一个 `mcp.json`，它所在的目录就是 MCP 的运行目录。

```text
project-data-mcp.zip
└─ project-data-mcp/
   ├─ mcp.json
   ├─ runtime/
   │  └─ python.exe
   ├─ server.py
   └─ packages/
      └─ ...完整依赖...
```

包可以再套一层目录；平台会自动找到 `mcp.json`。`command` 指向包内可执行文件时，路径
必须相对于 `mcp.json` 所在目录。Windows 和 Linux 的运行文件并不通用，上传包必须与
目标服务器操作系统匹配。

## 2. mcp.json

```json
{
  "schema_version": 1,
  "name": "project-data",
  "display_name": "项目数据查询",
  "version": "1.0.0",
  "description": "读取当前项目的结构化业务数据。",
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
- `command`：包内可执行文件，推荐连同 Python/Node 运行时一起打包；也可填写服务器
  `PATH` 中已有的单个命令名；
- `args`：传给启动命令的参数；
- `env`：仅传给该 MCP 进程的固定环境变量，不会返回给浏览器；
- `platform_capabilities`：可选的平台托管能力声明。普通 MCP 保持空数组；受信业务包
  可以声明 `dobby_agent_tools` 获取内部工具网关上下文，项目初始化编排包声明
  `dobby_database_interactions` 获取受智能体分配、会话范围和表白名单控制的标准数据库交互接口；
- `startup_timeout`：上传检测和会话首次启动的超时秒数；
- `execution_timeout`：单次 MCP 工具调用的超时秒数。

MCP 必须使用标准输入输出传输协议。普通日志不能写入 stdout，否则会破坏 JSON-RPC
通信；日志应写入 stderr 或独立日志文件。

平台还会覆盖注入 `AGENTSCOPE_USER_ID`、`AGENTSCOPE_AGENT_ID` 和
`AGENTSCOPE_SESSION_ID`。项目数据类 MCP 必须根据会话反查当前用户和项目并重新校验成员
权限；不要让模型直接传入用户 ID 或项目 ID。声明 `dobby_agent_tools` 的包还会获得专用
工具网关上下文；声明 `dobby_database_interactions` 的包会获得内部数据库交互地址和专用
服务令牌。这些值只存在于 MCP 子进程环境中，不会进入浏览器接口或上传包。

平台不向 MCP 注入数据库文件路径、数据库账号或原始 SQL 执行能力。初始化 MCP 只能按
已分配且标记为“工作流内部”的交互读取、创建或修改当前初始化会话的记录；每次写入都会重新检查数据表
白名单，并由平台补充项目、会话、用户、执行智能体和审计信息。因此切换 SQLite 或其他数据库时无需
重写 MCP 的业务流程。

## 3. 上传、升级与分配

1. 在智能体聊天页右侧切换到 `MCP`；
2. 点击“上传 MCP”并选择完整安装包；
3. 服务端解压到临时目录，真实启动 MCP 并调用 `tools/list`；
4. 只有启动成功的包才会进入平台目录；
5. 勾选要分配给当前智能体的 MCP，点击“保存分配”；
6. 下一次对话运行时自动装载；无需在工程管理平台重复配置。

更新时保持 `name` 不变并提高 `version`。已有智能体分配使用稳定的 `name`，因此更新后
不需要重新勾选；各会话在下次运行时切换到新版本。仍被任一智能体使用的 MCP 不允许
删除，应先取消分配。

## 4. 并发与生命周期

- 程序包只保存一份，但运行进程按 `(会话 ID, MCP name)` 隔离；
- 同一会话连续多轮对话复用同一个 MCP 进程，可保留会话内状态；
- 不同平台用户、管理端会话和协同智能体会话不会共享 MCP 进程状态；
- 会话删除时立即关闭对应进程；空闲超过 3600 秒也会自动关闭；
- 默认最多同时运行 128 个 MCP 进程，可通过 `.env` 中的
  `AGENTSCOPE_MCP_MAX_ACTIVE_INSTANCES` 调整。

这里的并发上限是服务器保护阈值，不是 MCP 工具的业务并发能力。数据库连接池、第三方
接口限流等仍应由各 MCP 自身正确处理。

## 5. 安全边界

上传的 MCP 是服务器本地程序，运行权限与 AgentScope 服务进程相同。平台会阻止 ZIP
路径穿越、符号链接、超大解压和包外启动命令，但这不是代码沙箱。因此上传权限只应开放
给可信管理人员，安装包也必须来自可信开发者。

声明 `dobby_database_interactions` 的包仍属于受信业务包。平台负责会话、用户、项目、字段
白名单和并发版本校验；MCP 负责业务流程、参数模型与跨分区校验，双方都不能绕过用户最终
确认后才正式入库的边界。

初始化流程不限制附件数量，也不限制 MinerU 结果 ZIP 内的文件数量；附件和结构化记录按
页循环读取。为防止异常压缩包耗尽服务器资源，附件解析仍会校验解压后总大小，但该校验
与文件数量无关。
