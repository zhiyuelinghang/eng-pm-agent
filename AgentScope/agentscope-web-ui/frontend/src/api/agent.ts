import { client } from './client';
import type {
	AgentListResponse,
	AgentView,
	AgentSchemaV2Response,
	CreateAgentRequest,
	CreateAgentResponse,
	PlatformSettings,
	MemorySettingsResponse,
	TestWeKnoraConnectionResponse,
	UpdateWeKnoraConnectionRequest,
	UpdatePlatformSettingsRequest,
	UpdateMemorySettingsRequest,
	WeKnoraApiKeyResponse,
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

	getMemorySettings: () =>
		client.get<MemorySettingsResponse>('/agent/platform/memory-settings'),

	updateMemorySettings: (body: UpdateMemorySettingsRequest) =>
		client.put<MemorySettingsResponse>('/agent/platform/memory-settings', body),

	resetMemorySettings: (expectedRevision: number) =>
		client.post<MemorySettingsResponse>('/agent/platform/memory-settings/reset', {
			expected_revision: expectedRevision,
		}),

	getWeKnoraConnection: () =>
		client.get<WeKnoraConnection>('/agent/platform/weknora-connection'),

	revealWeKnoraApiKey: () =>
		client.get<WeKnoraApiKeyResponse>(
			'/agent/platform/weknora-connection/api-key',
		),

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
