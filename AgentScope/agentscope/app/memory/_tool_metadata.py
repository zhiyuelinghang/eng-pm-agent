"""Memory tool display declarations, independent of the memory runtime/DB.

Both registration and history replay use this catalogue. Opening an old chat
must not require first executing a memory tool or importing the memory service.
"""

MEMORY_TOOL_TITLES = {
    "search_memory": "回顾相关信息",
    "add_memory": "记下重要信息",
    "forget_memory": "删除指定记忆",
    "learn_from_task": "记录复盘素材",
    "learning_feedback": "记录经验反馈",
}

# Names emitted by earlier memory tool interfaces. These aliases affect only
# history presentation; they do not register or enable obsolete tool actions.
LEGACY_MEMORY_TOOL_TITLES = {
    "memory_search": "回顾相关信息",
    "memory_read": "回顾相关信息",
    "memory_write": "记下重要信息",
}


def memory_presentations() -> dict[str, dict[str, str]]:
    return {
        name: {"label": title, "source": "registration", "category": "memory"}
        for name, title in {**LEGACY_MEMORY_TOOL_TITLES, **MEMORY_TOOL_TITLES}.items()
    }
