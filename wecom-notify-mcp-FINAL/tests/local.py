import json
from src.tools.send_text import send_text
from src.tools.send_markdown import send_markdown
from src.tools.send_image import send_image
from src.tools.get_status import get_status

print("=" * 50)
print("开始测试企业微信通知推送 MCP Server")
print("=" * 50)

# 1. 测试发送纯文本
print("\n>>> 测试 1: wecom_send_text")
res = send_text("default", "【Dobby 测试】来自 MCP 的文本消息")
print("结果:", json.dumps(res.to_dict(), ensure_ascii=False, indent=2))

# 2. 测试发送 Markdown
print("\n>>> 测试 2: wecom_send_markdown")
md = """
## 【整改通知】
> 任务编号：ZG-20260708-003
> 责任人：张三
> 截止时间：2026-07-10 17:00

**问题描述：** 3号基坑临边防护未完成

[查看详情](https://example.com/tasks/ZG-20260708-003)
"""
res = send_markdown("default", md)
print("结果:", json.dumps(res.to_dict(), ensure_ascii=False, indent=2))

# 3. 测试发送图片
print("\n>>> 测试 3: wecom_send_image")
# 请将 test.png 替换为你项目中实际的测试图片路径
res = send_image("default", "test.png")
print("结果:", json.dumps(res.to_dict(), ensure_ascii=False, indent=2))

# 4. 测试状态查询
print("\n>>> 测试 4: wecom_get_status")
res = get_status("default")
print("会话状态:", json.dumps(res.to_dict(), ensure_ascii=False, indent=2))

print("\n" + "=" * 50)
print("所有测试完成")
print("=" * 50)
