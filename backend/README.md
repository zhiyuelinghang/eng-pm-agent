# Dobby 后端

业务 API 使用 FastAPI、Pydantic 和 SQLAlchemy。标准运行使用 PostgreSQL，`DATABASE_URL`
必须显式配置；SQLite 分支供测试或兼容用途，不是默认启动配置。模型凭证与参数在
AgentScope 管理端配置，平台通过服务令牌调用共享模型。

从项目根目录启动和验证：

```powershell
.\start-frontend.bat
.\test-all.bat --suite structure --suite backend
```

启动脚本使用项目内嵌 `python-3.13.14\python.exe`。数据库结构需事先准备，启动不会
自动迁移。管理员初始化行为见 [main.py](app/main.py) 的 `seed_admin`；生产部署应检查
初始账号并修改密码，当前没有通过管理员环境变量替换该逻辑的机制。

- [main.py](app/main.py)：路由装配和生命周期；领域路由分布在各 `*_api.py`。
- [models.py](app/models.py)、[workspace_models.py](app/workspace_models.py)、[交互授权模型](app/database_interaction_assignment_model.py)：业务表定义；版本变更见 [Alembic 迁移](alembic/versions)。
- [config.py](app/config.py)：配置字段；[agentscope_client.py](app/agentscope_client.py)：智能体服务网关。
- [后端开发规范](../docs/开发规范/后端开发规范.md)、[测试规范](../docs/开发规范/测试规范.md)、[服务器部署说明](../服务器部署说明.md)。
