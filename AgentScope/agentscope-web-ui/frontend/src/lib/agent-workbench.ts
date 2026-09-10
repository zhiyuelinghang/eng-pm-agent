import type { AgentView, PlatformSettings } from '@/api/types';

export const DUTIES = [
	{
		key: 'main',
		field: 'global_main_agent_id',
		name: 'Dobby 总控',
		en: 'Dobby orchestrator',
		description: '承接首页对话，组织任务助手、知识库助手及已授权业务智能体完成工作。',
		descriptionEn:
			'Handle homepage conversations and coordinate task, knowledge and authorized business agents.',
		icon: 'bot',
	},
	{
		key: 'initializer',
		field: 'project_initializer_agent_id',
		name: '项目初始化',
		en: 'Project initialization',
		description: '仅在初始化页面解析项目资料，组织专项智能体生成并核验初始化草稿。',
		descriptionEn:
			'Only in the initialization page, coordinate specialists to prepare and validate project drafts.',
		icon: 'file',
	},
	{
		key: 'taskAssistant',
		field: 'task_assistant_agent_id',
		name: '任务助手',
		en: 'Task assistant',
		description: '梳理任务需求，拆解执行步骤，生成任务草稿。',
		descriptionEn: 'Clarify task requirements, break down the steps, and prepare task drafts.',
		icon: 'task',
	},
	{
		key: 'knowledgeAssistant',
		field: 'knowledge_assistant_agent_id',
		name: '知识库助手',
		en: 'Knowledge assistant',
		description: '专门查询项目知识库，依据资料回答问题并标明出处。',
		descriptionEn: 'Find project documents, answer from their contents, and cite the sources.',
		icon: 'book',
	},
] as const;
export type Duty = (typeof DUTIES)[number];

/** Resolve fixed duties by their configured IDs. */
export function agentDuty(agentId: string, settings: PlatformSettings): Duty | undefined {
	return DUTIES.find((duty) => settings[duty.field] === agentId);
}

/** Duty bindings define navigation groups; execution level and visibility do not. */
export function businessAgents(agents: AgentView[], settings: PlatformSettings) {
	const fixed = new Set(DUTIES.map((duty) => settings[duty.field]).filter(Boolean));
	return agents
		.filter((agent) => !fixed.has(agent.id))
		.sort(
			(a, b) =>
				a.data.platform_config.sort_order - b.data.platform_config.sort_order ||
				a.data.name.localeCompare(b.data.name),
		);
}

export function dutyStatus(duty: Duty, settings: PlatformSettings, agents: AgentView[]) {
	const id = settings[duty.field];
	if (!id) return 'empty';
	const agent = agents.find((item) => item.id === id);
	if (!agent) return 'unavailable';
	if (
		!agent.data.platform_config.enabled ||
		agent.data.model_policy.mode !== 'fixed' ||
		!agent.data.model_policy.chat_model_config
	)
		return 'invalid';
	if (duty.key === 'initializer' && !settings.project_initializer_validation_mcp)
		return 'invalid';
	return 'ready';
}
