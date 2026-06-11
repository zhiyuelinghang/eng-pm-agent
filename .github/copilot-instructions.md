# eng-pm-agent · 远程开发协作规则

> 本仓库在 **Linux 容器**（主机名 `devbox`）内开发，通过 VS Code Remote-SSH 连接，客户端是 Windows。项目根目录在容器内是 `/workspace/eng-pm-agent`。

## 远程路径

AI 调编辑工具读写文件时，文件路径一律使用完整 Remote URI：

```text
vscode-remote://ssh-remote+devbox/workspace/eng-pm-agent/<相对路径>
```

- 不带前缀时，工具可能把路径当成 Windows 客户端本地路径，出现 `File \workspace\... does not exist`。
- 改斜杠方向没有用，关键是补上 `vscode-remote://ssh-remote+devbox` 前缀。

## 文件操作

1. 改文件只用 VS Code 编辑工具，不用 `sed`、`perl`、`awk`、重定向或 `tee` 改代码。
2. 看文件只用 `read_file`，搜索定位用 `grep_search`、`file_search`、`semantic_search` 等 VS Code 工具。
3. 不要混用命令行改文件和编辑工具改文件，避免 VS Code 旧缓冲保存后覆盖磁盘改动。
4. 不建备份/副本文件（如 `*.bak`、`*.prev`、`*-backup-*`），历史版本交给 git。

## 终端使用

- 终端只用于运行程序、安装依赖、执行测试、查看 git 状态等运行类任务。
- 用户没有明确要求运行程序时，不用终端读取或修改代码文件。
- 提交或交付前可用 `git status` 检查，不提交 `.env`、令牌、虚拟环境、缓存和临时文件。

## 端口转发

项目服务如果跑在远程容器里，本地浏览器访问依赖 VS Code Remote-SSH 的 PORTS 端口转发：

1. 服务监听远程容器的 `0.0.0.0` 或 `127.0.0.1`。
2. 在 VS Code 底部 PORTS 面板手动或自动转发对应端口。
3. 本地浏览器访问 PORTS 面板显示的本地地址，优先使用 `127.0.0.1`。

