# 工程管理智能体

Dobby 将工程资料、项目初始化、任务管理、群聊与智能体协作接入同一业务平台。
本文件是项目阅读入口；各主题只维护下表对应的现行文档。功能是否已实现以源码和
对应测试为准，设计提案与版本记录不代替现行规则。

## 本地开发

所有命令均在仓库根目录执行。配置项见 [.env.example](.env.example)，Python 固定使用
项目内嵌的 `python-3.13.14\python.exe`；不要使用系统 Python、`py` 或 Conda 环境替代。

```powershell
.\start-all.bat
```

也可分别运行 `start_agentscope.bat` 和 `start-frontend.bat`。后者启动平台 API
（38430）和业务前端（38429）；AgentScope 提供智能体管理与执行服务。建议先启动
AgentScope，使业务平台创建会话时能够完成健康检查。

```powershell
.\一键停止全部服务.bat
.\一键停止全部服务.bat /dry-run
```

停止脚本按端口、PID、启动时间、可执行文件和服务类型核验进程身份。
服务登记与启停记录位于 `data/runtime/`；端口被其他程序占用时只报告冲突。

## 项目结构与事实入口

| 部分 | 职责与入口 |
| --- | --- |
| [业务前端](frontend/README.md) | Vue 3、TypeScript、Naive UI；页面入口见 [路由](frontend/src/router/index.ts)。 |
| [平台后端](backend/README.md) | FastAPI；[main.py](backend/app/main.py) 装配路由和后台服务，各领域 API 完成业务权限校验。 |
| [AgentScope](AgentScope/UPSTREAM.md) | 智能体运行核心与本项目扩展；本地装配见 [agentscope_dev_app.py](scripts/agentscope_dev_app.py)，[管理端](AgentScope/agentscope-web-ui/frontend/README.md) 使用 React。 |
| [MCP 包](mcp-packages) | 附件解析、初始化核验、任务引擎、数据建模及企业微信通知；包入口各自维护使用与构建方式。 |
| [utils](utils) | 记忆、学习、来源校验和共享持久化服务。 |
| [数据库模型](backend/app/models.py)与[迁移](backend/alembic/versions) | 平台模型、数据库修订和约束；AgentScope、记忆及任务引擎还有各自存储实现，不能只按业务模型重建全库。 |
| [scripts](scripts) | 启停、构建、安装、显式迁移和验证入口。 |
| [原型](原型)与[业务参考](docs/业务参考/真如项目/README.md) | 产品和业务输入；原型的工程基本信息文件仍被初始化解析测试引用。 |

平台业务数据使用 PostgreSQL 的 `platform` schema；任务引擎使用独立 schema。
AgentScope 保存对话正文、工具调用和协作过程，业务平台按授权映射读取，避免维护另一份
聊天正文。管理账号与业务账号分离，平台后端通过服务令牌访问 AgentScope，浏览器不直接
访问其内部 API。记忆访问按真实用户、项目、来源与运行场景取交集。

## 现行文档

| 要做什么 | 阅读入口 |
| --- | --- |
| 开发、评审与测试 | [开发规范](docs/开发规范/README.md) |
| 部署或更新服务器 | [服务器部署说明](服务器部署说明.md) |
| 使用智能体管理中心 | [操作手册](docs/操作说明/智能体管理中心全局操作说明.html) |
| 调整智能体职责与协作 | [智能体分工与协作规则](docs/操作说明/智能体分工与协作规则.md) |
| 修改记忆和学习 | [记忆与学习职责与运行规则](docs/操作说明/记忆与学习职责与运行规则.md) |
| 修改执行、停止和恢复 | [智能体运行自动管理](docs/操作说明/智能体运行自动管理.md) |
| 修改模型或图片输入 | [统一模型与原生图片输入](docs/操作说明/统一模型与原生图片输入.md) |
| 修改对话过程展示 | [工作状态展示规则](docs/开发规范/Dobby对话工作状态展示.md) |
| 分批导入或更新项目资料 | [项目资料分批导入与更新](docs/操作说明/项目资料分批导入与更新.md) |
| 开发或上传 MCP | [MCP 包上传与运行说明](docs/MCP包上传与运行说明.md) |
| 对接任务引擎 | [任务引擎入口](mcp-packages/task-engine/README.md)、[Dobby 接入指南](mcp-packages/task-engine/Dobby接入指南.md) |
| 修改资料问答 | [知识库助手接入](docs/知识库问答接入平台资料助手.md) |
| 修改群聊实时通信 | [群聊实时通信说明](docs/项目群聊实时通信说明.md) |
| 配置初始化团队与能力 | [初始化能力清单](AgentScope/dobby-skills/CAPABILITY_MATRIX.md)、[团队定义](AgentScope/project-initialization-team.json) |

初始化工作流由 [dobby-skills](AgentScope/dobby-skills) 中的技能定义；附件解析后由模型
创建计划、组织专项智能体写入隔离草稿，平台调用选定版本的核验 MCP。用户确认前不写入
正式项目数据。技能是运行资源，不能按普通说明删除，也不应在后端再复制一套流程。

普通业务数据访问经过受控数据库交互或语义工具、真实会话身份与权限检查。
任意 SQL 和宿主命令执行不属于智能体开放能力；平台各入口遵守同一工具策略。

## 验证与发布

```powershell
.\test-all.bat --list
.\test-all.bat --suite structure --suite backend --suite frontend
```

不带参数运行已登记的默认套件。两套前端及其他未登记测试的补充命令和适用范围见
[测试规范](docs/开发规范/测试规范.md)，不要把某次历史通过数量当作当前版本验收。

生产包使用开发机预构建前端和便携运行环境：

```powershell
.\生成服务器完整更新包.bat
```

服务器使用“服务器”前缀的入口。程序启动不建表、不自动迁移；数据库变更须先备份，
审阅并人工执行对应 SQL。数据库 SQL 和配置迁移的交付边界以部署手册为准。

## 参考材料

- [原始设计提案](docs/设计草案/README.md)：业务构想与需求输入，不代表已实现功能。
- [WeKnora 外部接口参考](docs/WeKnora接口参考.md)：外部服务接口示例，不作为本项目当前架构。
- [版本说明](docs/版本说明/2026-09-10-智能体协作与记忆学习升级.md)：记录版本变化和升级事项，不承诺各环境已完成升级。

临时日志、截图、执行结果与一次性脚本统一放入忽略目录 `artifacts/` 或 `scratch/`，
任务结束后清理。普通修复不新建说明、总结或验收文档；需长期维护的变化直接更新上表
对应文档。密钥、真实业务数据及本机配置不进入版本库。
