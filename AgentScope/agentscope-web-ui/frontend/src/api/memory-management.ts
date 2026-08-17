import { client } from './client';
import type {
	ManagedMemoryItem,
	MemoryManagementResponse,
	MemoryScopeType,
	UpdateMemoryScopeRequest,
} from './types';

export interface MemoryManagementFilters {
	platformUserId?: string;
	projectId?: string;
	scopeType?: MemoryScopeType;
	query?: string;
	limit?: number;
}

export const memoryManagementApi = {
	list: (filters: MemoryManagementFilters = {}) => {
		const params: Record<string, string> = {
			limit: String(filters.limit ?? 200),
		};
		if (filters.platformUserId) params.platform_user_id = filters.platformUserId;
		if (filters.projectId) params.project_id = filters.projectId;
		if (filters.scopeType) params.scope_type = filters.scopeType;
		if (filters.query?.trim()) params.query = filters.query.trim();
		return client.get<MemoryManagementResponse>('/memory-management/memories', params);
	},

	updateScope: (memoryId: string, body: UpdateMemoryScopeRequest) =>
		client.patch<ManagedMemoryItem>(
			`/memory-management/memories/${encodeURIComponent(memoryId)}/scope`,
			body,
		),

	delete: (memoryId: string) =>
		client.delete(`/memory-management/memories/${encodeURIComponent(memoryId)}`),
};
