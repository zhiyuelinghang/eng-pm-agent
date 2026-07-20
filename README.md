# 工程管理智能体

## 本地启动

在项目根目录运行：

```powershell
.\start-frontend.bat
```

启动脚本会在 `38430` 端口启动后端 API，在 `38429` 端口启动前端开发服务器。

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
- `doc`：MVP 需求、架构、接口和开发排期资料。
- `原型`：产品原型和智能体架构方案。
- `会议纪要`：项目评审与决策记录。
