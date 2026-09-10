"""Task editor generation uses the configured assistant and its assigned MCP."""
from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from task_engine.domain.models import Assignee, CalendarMode, IntervalUnit, RunMode, Site, StepSpec, TaskFlow, Trigger
from task_engine.generator.llm import AIFlowGenerationError

from .task_session_binding import create_bound_task_session, finish_bound_task_session


def flow_from_mcp(raw: dict, *, now: datetime, context: dict) -> TaskFlow:
    """Decode the native MCP result while retaining schedules and responsibility."""
    if raw.get('origin') != 'ai' or not raw.get('steps') or not isinstance(raw.get('trigger'), dict):
        raise ValueError('任务助手必须返回任务引擎生成的 AI 任务流')
    people = {str(item['ref']) for item in context.get('assignees', [])}

    def person(value):
        if not value:
            return None
        if str(value.get('ref')) not in people:
            raise ValueError('任务助手返回了当前项目之外的责任人')
        return Assignee(ref=str(value['ref']), display_name=str(value.get('name') or value.get('display_name') or ''))

    def moment(value):
        if not value:
            return None
        result = datetime.fromisoformat(value)
        tz = now.tzinfo or ZoneInfo('Asia/Shanghai')
        return result.astimezone(tz) if result.tzinfo else result.replace(tzinfo=tz)

    trigger = raw['trigger']
    site = raw.get('site')
    if site and str(site.get('ref')) not in {str(item['id']) for item in context.get('wbs_items', [])}:
        raise ValueError('任务助手返回了当前项目之外的工点')
    return TaskFlow(
        title=raw['title'], summary=raw.get('summary', ''), category=raw.get('category', 'general'),
        priority=raw.get('priority', 'normal'), origin='ai', origin_note=raw.get('origin_note', ''),
        trigger=Trigger(
            run_mode=RunMode(trigger.get('run_mode', 'once')), first_at=moment(trigger.get('first_at')) or now,
            interval_value=int(trigger.get('interval_value', 1)), interval_unit=IntervalUnit(trigger.get('interval_unit', 'week')),
            until=moment(trigger.get('until')), max_fires=trigger.get('max_fires'),
            calendar_mode=CalendarMode(trigger['calendar_mode']) if trigger.get('calendar_mode') else None,
            calendar_weekdays=tuple(trigger.get('calendar_weekdays') or []), calendar_day=trigger.get('calendar_day'),
        ),
        steps=tuple(StepSpec(
            name=step['name'], assignee=person(step.get('assignee')), due_offset_days=int(step.get('due_offset_days', 1)),
            deliverable=step.get('deliverable', ''), instruction=step.get('instruction', ''),
            requires_attachment=bool(step.get('requires_attachment')), optional=bool(step.get('optional')),
            automated=bool(step.get('automated')),
        ) for step in raw['steps']),
        site=Site(ref=str(site['ref']), name=site.get('name', ''), code=site.get('code', '')) if site else None,
        confirmer=person(raw.get('confirmer')), watchers=tuple(person(item) for item in raw.get('watchers', []) if item),
        tags=tuple(raw.get('tags') or []), scope=raw.get('scope') or {},
    )


class TaskAssistantGenerator:
    async def generate_async(self, requirement, *, now, assignees, context, generation_id=None):
        from .chat_api import _agentscope_client, _configured_task_assistant, _task_flow_from_agent_reply
        from .agentscope_client import AgentScopeGatewayError

        agent = await asyncio.to_thread(_configured_task_assistant)
        client = _agentscope_client()
        agent_id = str(agent['id'])
        user, project = context['current_user'], context['project']
        generation_id = generation_id or uuid4().hex
        facts = {**context, 'now': now.isoformat(), 'assignees': [
            {'ref': item.ref, 'name': item.display_name} for item in assignees
        ]}
        pending = asyncio.create_task(asyncio.to_thread(
            create_bound_task_session, client, agent=agent, user_id=user['ref'],
            project_id=project['id'], generation_id=generation_id,
        ))
        session_id = None
        try:
            session_id = await asyncio.shield(pending)
            pending = asyncio.create_task(asyncio.to_thread(
                client.trigger_chat, agent_id=agent_id, session_id=session_id,
                content=(f'用户正在任务管理页面生成任务草稿。需求：{requirement}\n'
                         '当前项目上下文：' + json.dumps(facts, ensure_ascii=False) + '\n'
                         '必须调用已分配的 generate_task_flow，传递上述上下文及责任人，'
                         f'generation_id={generation_id}，save=false；不得发布任务或创建计划。'
                         '直接返回工具生成的任务流，缺项保留为空，供用户在页面补充。'),
                sender_name=user['display_name'], user_message_id=uuid4().hex,
                metadata={'source': 'task_editor', 'generation_id': generation_id,
                          'platform_user_id': user['ref'], 'project_id': project['id']},
            ))
            message_id = await asyncio.shield(pending)
            reply = await asyncio.to_thread(client.wait_for_chat_reply, agent_id=agent_id,
                session_id=session_id, resolved_user_message_id=message_id)
            if reply.status != 'completed':
                await asyncio.to_thread(client.interrupt, agent_id=agent_id, session_id=session_id)
                raise ValueError('任务助手未完成草稿生成，请检查其模型与任务引擎配置后重试')
            result = flow_from_mcp(_task_flow_from_agent_reply(reply), now=now, context=facts)
            origin_token = await asyncio.to_thread(finish_bound_task_session, session_id, 'completed')
            # This reference is issued from the durable server binding, never from model output.
            result.scope['generation_origin_token'] = origin_token
            return result
        except asyncio.CancelledError:
            # Settle submission before interruption, so a late HTTP trigger cannot restart it.
            with suppress(Exception):
                submitted = await pending
                if session_id is None:
                    session_id = submitted
                if session_id is not None:
                    await asyncio.to_thread(client.interrupt, agent_id=agent_id, session_id=session_id)
                    await asyncio.to_thread(finish_bound_task_session, session_id, 'cancelled')
            raise
        except (AgentScopeGatewayError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            if session_id is not None:
                await asyncio.to_thread(finish_bound_task_session, session_id, 'failed')
            raise AIFlowGenerationError(str(exc)) from exc
