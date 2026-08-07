import { client } from './client';
import type {
	DatabaseInteraction,
	DatabaseTableInfo,
	DatabaseTableInteractionRequest,
	DatabaseTablePolicy,
} from './types';

export const databaseInteractionApi = {
	list: (agentId: string) =>
		client.get<DatabaseInteraction[]>(
			'/database-interactions/',
			{ agent_id: agentId },
			{ silent: true },
		),

	assign: (agentId: string, interactionIds: number[]) =>
		client.put<DatabaseInteraction[]>(`/database-interactions/assignments/${agentId}`, {
			interaction_ids: interactionIds,
		}),

	tables: () =>
		client.get<DatabaseTableInfo[]>(
			'/database-interactions/tables',
			undefined,
			{ silent: true },
		),

	policies: {
		list: () =>
			client.get<DatabaseTablePolicy[]>(
				'/database-interactions/policies',
				undefined,
				{ silent: true },
			),
	},

	interactions: {
		create: (payload: DatabaseTableInteractionRequest) =>
			client.post<DatabaseInteraction>('/database-interactions/interactions', payload),
		updateTable: (id: number, payload: DatabaseTableInteractionRequest) =>
			client.put<DatabaseInteraction>(
				`/database-interactions/interactions/${id}/table`,
				payload,
			),
		delete: (id: number) => client.delete(`/database-interactions/interactions/${id}`),
	},
};
