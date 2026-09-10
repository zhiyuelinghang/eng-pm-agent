import type {
	AgentCallConfig,
	AgentView,
	PlatformSettings,
	UpdateAgentRequest,
} from '../api/types';

/** Non-main agents use an explicitly selected list. */
export function collaborationSelection(config?: AgentCallConfig): string[] {
	return config?.scope === 'selected' ? [...config.allowed_agent_ids] : [];
}

export function collaborationCandidates(
	agent: AgentView,
	agents: AgentView[],
	mainDuty = false,
	settings?: PlatformSettings,
): AgentView[] {
	return agents
		.filter(
			(candidate) =>
				candidate.id !== agent.id &&
				candidate.id !== settings?.global_main_agent_id &&
				candidate.id !== settings?.project_initializer_agent_id &&
				candidate.data.platform_config.enabled &&
				(mainDuty
					? candidate.id === settings?.task_assistant_agent_id ||
						candidate.id === settings?.knowledge_assistant_agent_id ||
						candidate.data.platform_config.allow_global_main_call
					: candidate.data.invite_config.invitable),
		)
		.sort((left, right) => left.data.name.localeCompare(right.data.name));
}

/** This tab owns outgoing calls only. Incoming metadata belongs to the edit dialog. */
export function collaborationUpdate(selectedIds: string[]): UpdateAgentRequest {
	return {
		call_config: {
			scope: selectedIds.length ? 'selected' : 'none',
			allowed_agent_ids: [...new Set(selectedIds)],
		},
	};
}
