import { useCallback, useEffect, useState } from 'react';

import { databaseInteractionApi } from '@/api';
import type {
	DatabaseInteraction,
	DatabaseTableInfo,
	DatabaseTableInteractionRequest,
	DatabaseTablePolicy,
} from '@/api';

export function useDatabaseInteractions(agentId: string | null) {
	const [interactions, setInteractions] = useState<DatabaseInteraction[]>([]);
	const [policies, setPolicies] = useState<DatabaseTablePolicy[]>([]);
	const [tables, setTables] = useState<DatabaseTableInfo[]>([]);
	const [loading, setLoading] = useState(false);
	const [catalogError, setCatalogError] = useState<Error | null>(null);

	const refetch = useCallback(async () => {
		if (!agentId) {
			setInteractions([]);
			setPolicies([]);
			return;
		}
		setLoading(true);
		setCatalogError(null);
		try {
			const [nextInteractions, nextPolicies] = await Promise.all([
				databaseInteractionApi.list(agentId),
				databaseInteractionApi.policies.list(),
			]);
			setInteractions(nextInteractions);
			setPolicies(nextPolicies);
		} catch (reason) {
			setCatalogError(reason as Error);
		} finally {
			setLoading(false);
		}
	}, [agentId]);

	useEffect(() => {
		void refetch();
	}, [refetch]);

	const loadTables = useCallback(async () => {
		if (tables.length) return tables;
		const next = await databaseInteractionApi.tables();
		setTables(next);
		return next;
	}, [tables]);

	const assign = useCallback(
		async (interactionIds: number[]) => {
			if (!agentId) throw new Error('No agent selected');
			const next = await databaseInteractionApi.assign(agentId, interactionIds);
			setInteractions(next);
		},
		[agentId],
	);

	const createInteraction = useCallback(
		async (payload: DatabaseTableInteractionRequest) => {
			await databaseInteractionApi.interactions.create(payload);
			await refetch();
		},
		[refetch],
	);

	const updateTableInteraction = useCallback(
		async (id: number, payload: DatabaseTableInteractionRequest) => {
			await databaseInteractionApi.interactions.updateTable(id, payload);
			await refetch();
		},
		[refetch],
	);

	const removeInteraction = useCallback(async (id: number) => {
		await databaseInteractionApi.interactions.delete(id);
		await refetch();
	}, [refetch]);

	return {
		interactions,
		policies,
		tables,
		loading,
		catalogError,
		refetch,
		loadTables,
		assign,
		createInteraction,
		updateTableInteraction,
		removeInteraction,
	};
}
