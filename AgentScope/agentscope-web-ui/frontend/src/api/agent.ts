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
	WeKnoraFolderTreeResponse,
	SearchWeKnoraKnowledgeRequest,
	SearchWeKnoraKnowledgeResponse,
	CreateWeKnoraUrlKnowledgeRequest,
	WeKnoraKnowledgeMutationResponse,
	AskWeKnoraAgentRequest,
	AskWeKnoraAgentResponse,
	UpdateWeKnoraProjectBindingRequest,
	WeKnoraProjectBinding,
	WeKnoraProjectBindingListResponse,
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
		params: {
			page?: number;
			page_size?: number;
			folder_path?: string;
			folder_recursive?: boolean;
			keyword?: string;
		} = {},
	) =>
		client.get<WeKnoraKnowledgeListResponse>(
			`/agent/platform/weknora/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/knowledge`,
			Object.fromEntries(Object.entries({
				page: String(params.page ?? 1),
				page_size: String(params.page_size ?? 50),
				folder_path: params.folder_path,
				folder_recursive:
					params.folder_path !== undefined
						? String(params.folder_recursive ?? false)
						: undefined,
				keyword: params.keyword?.trim() || undefined,
			}).filter((entry): entry is [string, string] => entry[1] !== undefined)),
		),

	getWeKnoraFolderTree: (knowledgeBaseId: string) =>
		client.get<WeKnoraFolderTreeResponse>(
			`/agent/platform/weknora/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/knowledge/folders`,
		),

	searchWeKnoraKnowledge: (
		knowledgeBaseId: string,
		body: SearchWeKnoraKnowledgeRequest,
	) =>
		client.post<SearchWeKnoraKnowledgeResponse>(
			`/agent/platform/weknora/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/search`,
			body,
		),

	uploadWeKnoraKnowledge: (
		knowledgeBaseId: string,
		file: File,
		enableMultimodel = true,
		folderPath = '',
	) => {
		const form = new FormData();
		form.append('file', file);
		form.append('enable_multimodel', String(enableMultimodel));
		if (folderPath) form.append('folder_path', folderPath);
		return client.upload<WeKnoraKnowledgeMutationResponse>(
			`/agent/platform/weknora/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/knowledge/file`,
			form,
		);
	},

	createWeKnoraUrlKnowledge: (
		knowledgeBaseId: string,
		body: CreateWeKnoraUrlKnowledgeRequest,
	) =>
		client.post<WeKnoraKnowledgeMutationResponse>(
			`/agent/platform/weknora/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/knowledge/url`,
			body,
		),

	deleteWeKnoraKnowledge: (knowledgeId: string) =>
		client.delete(
			`/agent/platform/weknora/knowledge/${encodeURIComponent(knowledgeId)}`,
		),

	downloadWeKnoraKnowledge: (knowledgeId: string) =>
		client.stream(
			`/agent/platform/weknora/knowledge/${encodeURIComponent(knowledgeId)}/download`,
		),

	previewWeKnoraKnowledge: (knowledgeId: string) =>
		client.stream(
			`/agent/platform/weknora/knowledge/${encodeURIComponent(knowledgeId)}/preview`,
		),

	askWeKnoraAgent: (body: AskWeKnoraAgentRequest) =>
		client.post<AskWeKnoraAgentResponse>(
			'/agent/platform/weknora/agent-query',
			body,
		),

	listWeKnoraProjectBindings: () =>
		client.get<WeKnoraProjectBindingListResponse>(
			'/agent/platform/weknora/project-bindings',
		),

	updateWeKnoraProjectBinding: (
		projectId: number,
		body: UpdateWeKnoraProjectBindingRequest,
	) =>
		client.put<WeKnoraProjectBinding>(
			`/agent/platform/weknora/project-bindings/${projectId}`,
			body,
		),
};
