"""System memory rules derived from duties and trusted invocation context."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


SCOPES = ('user', 'user_project', 'project')


@dataclass(frozen=True)
class MemoryRules:
    read_scopes: tuple[str, ...]
    write_scopes: tuple[str, ...]
    learning_enabled: bool
    learning_use: bool = True


def memory_duty(settings: Any, agent_id: str) -> str | None:
    """Only explicit platform bindings define a duty; visibility grants none."""
    for duty, field in (
        ('main', 'global_main_agent_id'),
        ('initializer', 'project_initializer_agent_id'),
        ('taskAssistant', 'task_assistant_agent_id'),
        ('knowledgeAssistant', 'knowledge_assistant_agent_id'),
    ):
        if agent_id and getattr(settings, field, None) == agent_id:
            return duty
    return None


def memory_rules(
    *, duties: Sequence[str | None],
    entry_kind: str, delegated: bool, private: bool = True,
    input_is_derived: bool = False, inherited_no_learning: bool = False,
    inherited_no_memory: bool = False,
) -> MemoryRules:
    """Compute an upper bound; live identity, audience and sources narrow it.

    Duties are ordered from the current node to its root. The invocation's
    duties and business entry determine scopes for the whole delegated subtree;
    per-request user exclusions apply to every participant.
    """
    if not duties:
        raise ValueError('Memory rules require the complete invocation chain.')
    reads = set(SCOPES[1:] if delegated else SCOPES)
    writes = set(SCOPES)
    learning = True
    if entry_kind == 'group_chat' or not private:
        reads.intersection_update({'project'})
        writes.intersection_update({'project'})
        # Group messages have their own source switch and audience pipeline.
        learning = False
    if 'taskAssistant' in duties or entry_kind == 'task':
        writes.intersection_update({'user', 'user_project'})
    if 'knowledgeAssistant' in duties or entry_kind == 'knowledge':
        writes.intersection_update({'user_project'})
    if 'initializer' in duties or entry_kind == 'initialization':
        reads.intersection_update({'project'})
        writes.clear()
        learning = False
    if entry_kind == 'debug':
        # Debug memories are isolated under a synthetic management identity.
        learning = False
    if input_is_derived:
        writes.clear()
        learning = False
    if inherited_no_learning:
        learning = False
    if inherited_no_memory:
        return MemoryRules((), (), False, False)
    return MemoryRules(
        tuple(scope for scope in SCOPES if scope in reads),
        tuple(scope for scope in SCOPES if scope in writes),
        learning,
    )


def agent_can_use_shared_memory(agent_record: Any | None) -> bool:
    """All enabled agents can use authorized memory under the runtime rules."""
    config = getattr(getattr(agent_record, 'data', None), 'platform_config', None)
    return bool(config is not None and config.enabled)
