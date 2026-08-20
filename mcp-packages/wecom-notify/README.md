# 企业微信通知推送 MCP

本包源自 `origin/Enterprise-Wechat-Notification` 的群机器人技术路线，并完成了平台化整理：保留文本、Markdown、图片、图文和状态查询 5 个工具，统一使用标准 MCP stdio 协议，同时补充 Webhook 域名校验、超时、错误信封与可自动化测试的 HTTP 传输层。

## 工具

- `wecom_send_text`：发送文本，可通过企业微信 UserID 或手机号提醒成员。
- `wecom_send_markdown`：发送 Markdown 通知。
- `wecom_send_image`：发送不超过 2MB 的本地图片或 data URI。
- `wecom_send_news`：发送 1 至 8 条图文消息。
- `wecom_get_status`：读取当前进程内的发送统计。

平台运行时通过会话绑定的内部网关发送：MCP 只能获得当前 AgentScope 会话和专用服务令牌，群机器人 Webhook 始终留在工程平台后端密文存储中。独立运行时仍可通过 `WECOM_WEBHOOK_URL` 提供群机器人 Webhook。

平台自动任务通知不依赖 MCP 自主调用，而是从任务引擎结果写入 PostgreSQL 通知队列，再由宿主通知适配器可靠投递。

群机器人只能向群聊发消息，无法私聊，也没有交互回调。任务的处理与验收仍在 Dobby 平台完成。
