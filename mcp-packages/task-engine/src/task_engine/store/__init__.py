"""持久层适配器。

适配器按需从具体模块导入，避免 SQLite/MCP 路径无条件加载 PostgreSQL 依赖。
"""
