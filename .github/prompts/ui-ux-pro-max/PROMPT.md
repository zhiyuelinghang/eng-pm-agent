# UI/UX Pro Max 项目用法

本工具提供本地样式、配色、排版、图表与交互资料。仅在用户调用此工作流时使用；
项目技术栈、现行规范和用户要求优先。规则入口见[开发规范](../../../docs/开发规范/README.md)。

## 使用方式

在仓库根目录使用项目内嵌 Python，先判断变更位于 Vue 业务前端还是 React 管理端，
沿用对应组件与主题，不默认改为另一套技术栈。

```powershell
.\python-3.13.14\python.exe .github/prompts/ui-ux-pro-max/scripts/search.py "工程管理 工作台" --design-system
.\python-3.13.14\python.exe .github/prompts/ui-ux-pro-max/scripts/search.py "keyboard focus" --domain ux
.\python-3.13.14\python.exe .github/prompts/ui-ux-pro-max/scripts/search.py "responsive form" --stack vue
.\python-3.13.14\python.exe .github/prompts/ui-ux-pro-max/scripts/search.py "state effects" --stack react
```

搜索结果直接用于当前分析，不默认运行 `--persist`，不生成独立设计系统、页面说明或验收报告。
用户明确需要保留的长期设计规则应合入现有规范；临时输出放入被忽略目录，任务结束清理。

## 查询范围

| 参数 | 内容 |
| --- | --- |
| `--design-system` | 按产品及场景组合样式建议，仅供参考。 |
| `--domain product/style/color/typography` | 产品类型、视觉风格、配色和字体。 |
| `--domain ux/web/react` | 交互、可访问性和渲染性能。 |
| `--domain chart/landing` | 图表选择与页面信息组织。 |
| `--stack vue/react/shadcn` | 对应栈的实现建议，按项目实际组件选择。 |

完整参数以[搜索程序](scripts/search.py)为准，数据位于[data](data)。

## 应用建议时核对

- 保留现有业务流程、权限、表单草稿和错误处理，设计资料不能覆盖业务规则。
- 可见文字不小于 12px，提供标签、键盘焦点和可读对比度，状态不能只靠颜色区分。
- 沿用项目图标、主题和组件，不为一次修改引入新的设计体系。
- 检查布局滚动、长文本、加载/空态/错误与小屏操作，不靠字体缩小隐藏问题。
- 浏览器操作遵守用户授权；没有实际检查的项目，不宣称已完成视觉验收。
- 开发经过和验证结果在任务回复中说明，不自动写入仓库。
