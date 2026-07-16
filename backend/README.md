# 工程智管家后端

后端使用 FastAPI + SQLAlchemy，默认以 SQLite 启动，部署时通过 `DATABASE_URL` 切换到 PostgreSQL。

项目根目录已提供 `.env.example`；首次运行前复制为 `.env` 并填入 `JWT_SECRET`。如需接入真实模型服务，同时填写 `AI_API_KEY`、`AI_BASE_URL` 与 `AI_MODEL`。

```powershell
D:\ProgramData\anaconda3\Scripts\conda.exe run -n base pip install -r backend/requirements.txt
D:\ProgramData\anaconda3\Scripts\conda.exe run -n base uvicorn app.main:app --app-dir backend --reload --port 8000
```

首次启动会创建开发管理员：`admin / ChangeMe123!`。部署前必须通过环境变量和初始化流程替换该账号与 `JWT_SECRET`。
