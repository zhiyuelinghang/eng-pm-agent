import { useState, useEffect, useCallback } from 'react';

import { workspaceApi } from '@/api';
import type { Skill, UpdateSkillRequest, WorkspaceTool } from '@/api';

export function useWorkspace(agentId: string | null, sessionId: string | null) {
	const [skills, setSkills] = useState<Skill[]>([]);
	const [tools, setTools] = useState<WorkspaceTool[]>([]);
	const [skillsLoading, setSkillsLoading] = useState(false);
	const [toolsLoading, setToolsLoading] = useState(false);
	const [error, setError] = useState<Error | null>(null);

	const refetchSkills = useCallback(async () => {
		if (!agentId || !sessionId) {
			setSkills([]);
			return;
		}
		setSkillsLoading(true);
		try {
			setSkills(await workspaceApi.skill.list(agentId, sessionId));
		} catch (e) {
			setError(e as Error);
		} finally {
			setSkillsLoading(false);
		}
	}, [agentId, sessionId]);

	const refetchTools = useCallback(async () => {
		if (!agentId) {
			setTools([]);
			return;
		}
		setToolsLoading(true);
		try {
			setTools(await workspaceApi.tool.list(agentId, sessionId));
		} catch (e) {
			setError(e as Error);
		} finally {
			setToolsLoading(false);
		}
	}, [agentId, sessionId]);

	useEffect(() => {
		refetchSkills();
	}, [refetchSkills]);
	useEffect(() => {
		refetchTools();
	}, [refetchTools]);

	const addSkill = useCallback(
		async (skillPath: string) => {
			if (!agentId || !sessionId) throw new Error('No agent/session selected');
			await workspaceApi.skill.add(agentId, sessionId, { skill_path: skillPath });
			await refetchSkills();
		},
		[agentId, sessionId, refetchSkills],
	);

	const removeSkill = useCallback(
		async (skillName: string) => {
			if (!agentId || !sessionId) throw new Error('No agent/session selected');
			await workspaceApi.skill.remove(skillName, agentId, sessionId);
			await refetchSkills();
		},
		[agentId, sessionId, refetchSkills],
	);

	const updateSkill = useCallback(
		async (skillName: string, update: UpdateSkillRequest) => {
			if (!agentId || !sessionId) throw new Error('No agent/session selected');
			await workspaceApi.skill.update(skillName, agentId, sessionId, update);
			await refetchSkills();
		},
		[agentId, sessionId, refetchSkills],
	);

	return {
		error,
		skills,
		skillsLoading,
		addSkill,
		updateSkill,
		removeSkill,
		tools,
		toolsLoading,
		refetchTools,
	};
}
