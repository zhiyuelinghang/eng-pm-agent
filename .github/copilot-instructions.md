# eng-pm-agent · 协作规则

> 本仓库在 **Linux 容器**（主机名 `devbox`）内开发，通过 VS Code Remote-SSH 连接，客户端是 Windows。项目根目录在容器内是 `/workspace/eng-pm-agent`。

## 🚫 铁律：全程用编辑工具，放弃命令行改/看代码

这是本仓库**最高优先级**规则，违反视为严重错误。

1. **改文件** → 只用编辑工具（`replace_string_in_file` / `multi_replace_string_in_file` / `create_file`）。
2. **看 / 验证文件** → 只用 `read_file`。带远程前缀读到的就是容器磁盘的真实最新内容，它本身就是"真相来源"。
3. **搜索 / 定位** → 用 `grep_search` / `file_search` / `semantic_search` 等 VS Code 工具。
4. **绝对禁止用命令行做任何代码相关操作**：
   - 改文件：`sed` / `perl` / `awk` / 重定向（`>` `>>`）/ `tee` —— **绝对禁止**。
   - 看/验证：`grep` / `curl` / `cat` / `head` / `tail` —— **不必要，弃用**（编辑工具读取已是真相来源，命令行纯属多余且增加犯错面）。
5. **工具失败时直接停下来反馈用户**，不要用命令行兜底。兜底往往就是出错的起点。

**唯一例外**：用户明确要求"运行程序"时（如启动 `uvicorn`、`git status`、安装依赖）才用终端 —— 那属于运行程序，不是看/改代码。

### 为什么（实测教训）

文件在 VS Code 编辑器打开时，命令行（`sed` 等）改了磁盘，编辑器仍持有旧内容缓冲；一旦保存就把命令的改动**覆盖还原**，导致「明明改了又变回去 / 改动丢失」。曾因此整轮样式美化几乎全部丢失。编辑工具全程操作则不会有此问题。

## ⚠️ 编辑工具必须带远程路径前缀

AI 调编辑工具（读/写）时，文件路径一律用完整 Remote URI：

```
vscode-remote://ssh-remote+devbox/workspace/eng-pm-agent/<相对路径>
```

- 不带前缀会报错 `File \workspace\...\xxx does not exist`（路径被 Windows 客户端解析成反斜杠）。
- 改斜杠方向（`/` ↔ `\`）没用，问题在**缺前缀**，补上即可。

## 前端 / 界面规范

- **界面文案中文就用中文，不要中英混排**（专有名词如 Python、Cron、Redis、MinIO、JSON 等例外）。
- 改前端（`gateway/app/static/`）后**刷新浏览器即可**，无需重启后端（`main.py` 用 `FileResponse` 每次请求读盘）。
- 遵循「前端审美判断层」：每视图一个焦点、留白是结构、每种颜色有理由、能删则删、阴影优先于边框、为交互态（focus/active/disabled/loading/empty/error）负责、不用渐变按钮/文字、不用魔法数字。详见 [gateway/前端样式开发指南.md](../gateway/前端样式开发指南.md)。

## 其他纪律

- **不建备份/副本文件**（`*-backup-*`、`*.bak`、`*.prev`）。要历史版本用 git。
- 改 `.py` 需重启 uvicorn（或用 `--reload`）。
- 提交前 `git status` 确认无 `.env`、无令牌、无临时文件。

## 分主题规则（按文件自动加载）

更详细的项目规则已按主题拆分到 `.github/instructions/`，编辑对应文件时自动生效：

- [网关架构与后端](instructions/网关架构与后端.instructions.md) — `gateway/app/**/*.py`：架构、加接口、profile、安全红线
- [数据库](instructions/数据库.instructions.md) — `gateway/app/{models,database,schemas}.py`：建表、表字段、连库
- [前端工程机制](instructions/前端工程机制.instructions.md) — `gateway/app/static/**`：iframe 切换、刷新即生效
- [前端开发指南](instructions/前端开发指南.instructions.md) — UI 文件：审美判断层
- [开发环境与启动](instructions/开发环境与启动.instructions.md) — `gateway/**`：安装、.env、启动、端口转发、FAQ
