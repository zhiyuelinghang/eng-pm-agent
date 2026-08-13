import { client } from './client';
import type {
	AgentListResponse,
	AgentView,
	AgentSchemaV2Response,
	CreateAgentRequest,
	CreateAgentResponse,
	PlatformSettings,
	TestWeKnoraConnectionResponse,
	UpdateWeKnoraConnectionRequest,
	UpdatePlatformSettingsRequest,
	WeKnoraConnection,
	WeKnoraKnowledgeBaseListResponse,
	WeKnoraKnowledgeListResponse,
	UpdateAgentRequest,
} from './types';

export const agentApi = {
	list: () => client.get<AgentListResponse>('/agent/'),

	getSchema: () => client.get<AgentSchemaV2Response>('/agent/schema/v2'),

	create: (body: CreateAgentRequest, options?: { silent?: boolean }) =>
		client.post<CreateAgentResponse>('/agent/', body, undefined, options),

	update: (agentId: string, body: UpdateAgentRequest, options?: { silent?: boolean }) =>
		client.patch<AgentView>(`/agent/${agentId}`, body, undefined, options),

	delete: (agentId: string) => client.delete(`/agent/${agentId}`),

	getPlatformSettings: () => client.get<PlatformSettings>('/agent/platform/settings'),

	updatePlatformSettings: (body: UpdatePlatformSettingsRequest) =>
		client.put<PlatformSettings>('/agent/platform/settings', body),

	getWeKnoraConnection: () =>
		client.get<WeKnoraConnection>('/agent/platform/weknora-connection'),

	updateWeKnoraConnection: (body: UpdateWeKnoraConnectionRequest) =>
		client.put<WeKnoraConnection>('/agent/platform/weknora-connection', body),

	testWeKnoraConnection: (body: UpdateWeKnoraConnectionRequest) =>
		client.post<TestWeKnoraConnectionResponse>(
			'/agent/platform/weknora-connection/test',
			body,
		),

	listWeKnoraKnowledgeBases: () =>
		client.get<WeKnoraKnowledgeBaseListResponse>(
			'/agent/platform/weknora/knowledge-bases',
		),

	listWeKnoraKnowledge: (
		knowledgeBaseId: string,
		params: { page?: number; page_size?: number } = {},
	) =>
		client.get<WeKnoraKnowledgeListResponse>(
			`/agent/platform/weknora/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/knowledge`,
			{
				page: String(params.page ?? 1),
				page_size: String(params.page_size ?? 50),
			},
		),
};
