import { client } from './client';
import type { ManagedMemoryItem, MemoryManagementResponse, MemoryScopeType, MemoryVersion, MemoryIndexJob, LegacyMemoryReview, LearningDashboard, LearningReview, LearningFeedback } from './types';

export interface MemoryManagementFilters {
	platformUserId?: string;
	projectId?: string;
	scopeType?: MemoryScopeType;
	query?: string;
	status?: 'active' | 'candidate' | 'inactive' | 'deleted';
	memoryType?: string;
	origin?: string;
	offset?: number;
	limit?: number;
}

export const memoryManagementApi = {
	list: (filters: MemoryManagementFilters = {}) => {
		const params: Record<string, string> = { limit: String(filters.limit ?? 50), offset: String(filters.offset ?? 0) };
		if (filters.platformUserId) params.platform_user_id = filters.platformUserId;
		if (filters.projectId) params.project_id = filters.projectId;
		if (filters.scopeType) params.scope_type = filters.scopeType;
		if (filters.query?.trim()) params.query = filters.query.trim();
		if (filters.status) params.record_status = filters.status;
		if (filters.memoryType) params.memory_type = filters.memoryType;
		if (filters.origin) params.origin = filters.origin;
		return client.get<MemoryManagementResponse>('/memory-management/memories', params);
	},
	update: (id: string, body: { expected_version: number; content?: string; scope_type?: MemoryScopeType;
		project_id?: string; platform_user_id?: string; publish?: boolean; status?: 'active' | 'candidate' }) =>
		client.patch<ManagedMemoryItem>(`/memory-management/memories/${encodeURIComponent(id)}`, body),
	delete: (id: string, version: number) => client.delete(`/memory-management/memories/${encodeURIComponent(id)}?expected_version=${version}`),
	history: (id: string) => client.get<MemoryVersion[]>(`/memory-management/memories/${encodeURIComponent(id)}/history`),
	jobs: () => client.get<MemoryIndexJob[]>('/memory-management/index-jobs'),
	retry: (id: string) => client.post(`/memory-management/memories/${encodeURIComponent(id)}/retry-index`, {}),
	legacy: () => client.get<LegacyMemoryReview[]>('/memory-management/legacy-review'),
	assignLegacy: (id: string, body: { scope_type: MemoryScopeType; platform_user_id: string; project_id: string; content: string; publish: boolean }) =>
		client.post<ManagedMemoryItem>(`/memory-management/legacy-review/${encodeURIComponent(id)}/assign`, body),
	learning: (offset = 0, state = '') => client.get<LearningDashboard>('/memory-management/learning', { offset: String(offset), limit: '30', ...(state ? { state } : {}) }),
	learningAction: (eventId: string, action: 'retry' | 'cancel') => client.post(`/memory-management/learning/events/${encodeURIComponent(eventId)}/${action}`, {}),
	review: (id: string, body: LearningReview) => client.post<ManagedMemoryItem>(`/memory-management/memories/${encodeURIComponent(id)}/learning-review`, body),
	feedback: (id: string) => client.get<LearningFeedback[]>(`/memory-management/memories/${encodeURIComponent(id)}/feedback`),
	sendFeedback: (id: string, body: { expected_version: number; outcome: 'success' | 'failure' | 'irrelevant'; evidence: string; request_id: string }) => client.post(`/memory-management/memories/${encodeURIComponent(id)}/feedback`, body),
	derive: (ids: string[], action: 'consolidate' | 'skill_compile', note: string) => client.post('/memory-management/learning/derive', { memory_ids: ids, action, note }),
	document: (id: string) => client.get<{ filename: string; content: string }>(`/memory-management/memories/${encodeURIComponent(id)}/learning-document`),
};
