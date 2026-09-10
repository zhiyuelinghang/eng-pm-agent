# Dobby 对话工作状态展示

## 用户可见行为

聊天按原顺序保留思考、每条调用记录和回答。思考生成时展开，结束后默认收起，用户
可随时查看；历史记录遵守相同规则。调用记录使用中文工作描述和真实执行状态，
隐藏函数名、参数和原始返回值。协作及下级记录保留，但不复制内部邀请参数。
工具结果通过助手答复与附件呈现，工作提示不能替代逐条记录。

失败显示简洁原因，不展示错误堆栈。没有结果时明确说明。需要业务确认时，展示服务端
提供的对象、影响和前后变化，并保留回复标识和确认版本；缺少可读预览时不能盲目确认。
旁观者只查看，停止中或停止后不再提供可执行确认按钮。

## 展示描述的来源

工具注册信息提供 `presentation = {label, source, category}`，执行状态来自实际事件。
业务前端不维护第二套名称表，也不从函数名、SQL、参数或返回值猜测工作内容。

- 普通工具使用 `display_name`。
- MCP 使用 `Tool.title`，缺失时使用 `annotations.title`。
- 数据库交互使用目录的业务 `display_name`。
- 无有效标题时，按已知来源和只读属性显示通用提示；展示描述不参与权限判断。
- 记忆读取/查询显示“回顾相关信息”，保存显示“记下重要信息”，标题由轻量元数据共用。

Toolkit 在已有目录查询完成后建立本次调用快照；发送开始事件时只读内存，不额外调用
模型、发现 MCP 或访问数据库。模型提供的同名字段不能覆盖注册信息。

## 实时、历史与恢复

`TOOL_CALL_START.presentation` 写入 `ToolCallBlock.presentation`，随消息 JSON 保存；
协作进度、待确认与恢复上下文保留同一快照。过去的真实快照不随工具改名或卸载重算。

旧消息缺少快照或只有通用描述时，历史接口可按当前工具注册、缓存 MCP 目录和数据库
业务目录补齐，标记为 `catalog_backfill`；不改写原始消息和执行结果。目录故障或来源
不明确时使用通用描述，不能阻断历史读取。目录按登录用户和智能体隔离缓存。

记忆历史标题不依赖记忆运行模块的加载时机；历史别名只服务展示，不能触发模型、
记忆服务或远程目录查询。新增工具在注册位置补充标题，避免前端补丁。

## 实现与验证入口

- [工具展示协议](../../AgentScope/agentscope/tool/_presentation.py)
- [历史补齐](../../AgentScope/agentscope/app/_service/_history_tool_presentation.py)
- [记忆展示元数据](../../AgentScope/agentscope/app/memory/_tool_metadata.py)
- [注册与事件测试](../../AgentScope/tests/test_tool_work_presentation.py)
- [历史与冷启动测试](../../AgentScope/tests/test_history_tool_presentation.py)
- [业务前端测试](../../frontend/tests)
