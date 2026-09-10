# 工程管理业务前端

本目录使用 Vue 3、TypeScript、Vite、Naive UI、Pinia、Vue Router 和 Axios，负责工程
业务页面。智能体管理端是独立的 [React 工程](../AgentScope/agentscope-web-ui/frontend/README.md)。

在本目录执行：

```powershell
npm run dev
npm run check
```

`check` 包含 Node 测试、Vue/TypeScript 类型检查和生产构建，具体命令以
[package.json](package.json) 为准。联动后端启动使用项目根目录的 `start-frontend.bat`。

- [src/router/index.ts](src/router/index.ts)：实际页面路由及访问入口。
- [src/views/workspace](src/views/workspace)：业务工作区；[src/components](src/components)：组件。
- [src/api](src/api)、[src/stores](src/stores)：请求与共享状态；[tests](tests)：现有自动测试。
- [前端开发规范](../docs/开发规范/前端开发规范.md)、[测试规范](../docs/开发规范/测试规范.md)。两套前端字体均不得小于 12px。
