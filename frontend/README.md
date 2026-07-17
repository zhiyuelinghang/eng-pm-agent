# Frontend

Dobby 前端采用独立 Web 工程，不使用 Python 前端。

推荐技术栈：

- Vue 3
- TypeScript
- Vite
- Element Plus
- Vue Router
- Pinia
- Axios 或基于 OpenAPI 生成的 API Client

前端通过 FastAPI 提供的 JSON API 与后端交互，负责页面路由、表格表单、任务操作、审核交互、文件上传和异步作业进度展示。

后续初始化 Vite 工程后，建议目录结构：

```text
frontend/
├── package.json
├── vite.config.ts
├── index.html
└── src/
    ├── api/
    ├── router/
    ├── stores/
    ├── views/
    ├── components/
    ├── styles/
    └── types/
```

当前目录先保留说明文件，避免在方案阶段生成未验证的依赖和脚手架文件。
