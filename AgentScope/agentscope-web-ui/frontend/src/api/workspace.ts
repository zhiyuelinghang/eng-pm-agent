import { client } from './client';
import type {
	AddSkillRequest,
	MCPClient,
	MCPClientStatus,
	Skill,
	UpdateSkillRequest,
	WorkspaceTool,
} from './types';

export const workspaceApi = {
	tool: {
		list: (agentId: string, sessionId?: string | null) =>
			client.get<WorkspaceTool[]>('/workspace/tool', {
				agent_id: agentId,
				...(sessionId ? { session_id: sessionId } : {}),
			}),
	},

	mcp: {
		list: (agentId: string, sessionId: string) =>
			client.get<MCPClientStatus[]>('/workspace/mcp', {
				agent_id: agentId,
				session_id: sessionId,
			}),

		add: (agentId: string, sessionId: string, mcp: MCPClient) =>
			client.post<void>('/workspace/mcp', mcp, { agent_id: agentId, session_id: sessionId }),

		remove: (mcpName: string, agentId: string, sessionId: string) =>
			client.delete(`/workspace/mcp/${mcpName}`, {
				agent_id: agentId,
				session_id: sessionId,
			}),
	},

	skill: {
		list: (agentId: string, sessionId: string) =>
			client.get<Skill[]>('/workspace/skill', { agent_id: agentId, session_id: sessionId }),

		add: (agentId: string, sessionId: string, body: AddSkillRequest) =>
			client.post<void>('/workspace/skill', body, {
				agent_id: agentId,
				session_id: sessionId,
			}),

		update: (skillName: string, agentId: string, sessionId: string, body: UpdateSkillRequest) =>
			client.put<void>(`/workspace/skill/${encodeURIComponent(skillName)}`, body, {
				agent_id: agentId,
				session_id: sessionId,
			}),

		remove: (skillName: string, agentId: string, sessionId: string) =>
			client.delete(`/workspace/skill/${encodeURIComponent(skillName)}`, {
				agent_id: agentId,
				session_id: sessionId,
			}),
	},
};
