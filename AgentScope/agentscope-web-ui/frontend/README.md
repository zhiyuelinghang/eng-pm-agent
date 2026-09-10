# Dobby 智能体管理前端

本目录使用 React、TypeScript、Vite、Tailwind CSS 和 Radix UI，负责智能体、模型、
工具及记忆管理。它与工程管理业务端的 [Vue 前端](../../../frontend/README.md) 分别构建。

联动服务使用项目根目录的 `start_agentscope.bat`。在本目录执行管理端检查：

```powershell
pnpm exec node --test tests/*.test.mjs
pnpm run lint
pnpm run build
```

构建包含 TypeScript 检查和 Vite 打包，命令以 [package.json](package.json) 为准。
当前根目录 `test-all.bat` 不运行这里的测试、lint 或构建，修改管理端时需单独执行。

- [src/App.tsx](src/App.tsx)、[src/pages](src/pages)：路由装配和页面。
- [src/api](src/api)、[src/hooks](src/hooks)、[src/lib](src/lib)：接口、状态协调和可测试逻辑。
- [Vite 配置](vite.config.ts)：开发代理；本项目服务装配见 [agentscope_dev_app.py](../../../scripts/agentscope_dev_app.py)。
- [前端开发规范](../../../docs/开发规范/前端开发规范.md)、[测试规范](../../../docs/开发规范/测试规范.md)。字体不得小于 12px。
