"""拒绝旧版把企业微信专业 MCP 直接分配给 Dobby 的操作。"""

from __future__ import annotations


def assign() -> None:
    """Keep legacy automation from reopening Dobby's professional toolset."""

    raise RuntimeError(
        "该脚本已停用：Dobby 不再直接持有企业微信通知 MCP。"
        "如需智能体主动发送通知，请在管理中心创建专用通知智能体，"
        "将 wecom-notify 只分配给该智能体，并配置 Dobby 调用许可与人工确认。",
    )


if __name__ == "__main__":
    assign()
