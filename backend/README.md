# Dobby 后端

后端使用 FastAPI + SQLAlchemy，默认以 SQLite 启动，部署时通过 `DATABASE_URL` 切换到 PostgreSQL。

## Python 运行环境约定（重要）

本项目启动脚本固定使用项目根目录下的便携 Python：`python-3.13.14\python.exe`。后端启动、依赖核验和本地调试均应优先使用该解释器，不使用系统 `python`、`py` 或 Anaconda `base` 的环境状态判断项目是否缺少依赖。

如需切换到 Conda 环境，必须明确修改 `start-frontend.bat` 并同步更新项目根目录 `README.md`；便携运行时缺失时不要静默回退到其他 Python 环境。

项目根目录已提供 `.env.example`；首次运行前复制为 `.env` 并填入 `JWT_SECRET`。模型凭证与参数统一在 AgentScope 管理端配置，并为平台总控选择固定模型；工程平台通过 `AGENTSCOPE_SERVICE_TOKEN` 使用该配置。

```powershell
.\python-3.13.14\python.exe -m pip install -r backend/requirements.txt
.\python-3.13.14\python.exe -m uvicorn app.main:app --app-dir backend --reload --port 38430
```

首次启动会创建开发管理员：`admin / ChangeMe123!`。部署前必须通过环境变量和初始化流程替换该账号与 `JWT_SECRET`。
