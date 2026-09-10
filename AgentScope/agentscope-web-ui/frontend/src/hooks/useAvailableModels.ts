import { useState, useEffect, useCallback } from 'react';

import { credentialApi } from '@/api';
import type { CredentialView, ModelCard } from '@/api';

export interface CredentialWithModels {
	credential: CredentialView;
	models: ModelCard[];
}

/**
 * Fetches all credentials and their available models, grouped by provider type.
 * Provider type is read from `credential.data.type`.
 * Credentials without a `type` field or whose model fetch fails are silently skipped.
 */
export function useAvailableModels(enabled = true) {
	const [groups, setGroups] = useState<Record<string, CredentialWithModels[]>>({});
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<Error | null>(null);

	const refetch = useCallback(async () => {
		if (!enabled) return;
		setLoading(true);
		setError(null);
		try {
			const { credentials } = await credentialApi.list();
			const result: Record<string, CredentialWithModels[]> = {};
			const failures: Error[] = [];

			await Promise.all(
				credentials.map(async (credential) => {
					const type = credential.data.type as string | undefined;
					if (!type) return;
					if (!result[type]) result[type] = [];
					try {
						const { models } = await credentialApi.models(credential.id);
						result[type].push({
							credential,
							models: models.filter((model) => model.enabled),
						});
					} catch (error) {
						failures.push(error instanceof Error ? error : new Error(String(error)));
						result[type].push({ credential, models: [] });
					}
				}),
			);

			setGroups(result);
			if (failures.length) setError(failures[0]);
		} catch (e) {
			setError(e as Error);
		} finally {
			setLoading(false);
		}
	}, [enabled]);

	useEffect(() => {
		refetch();
	}, [refetch]);

	return { groups, loading, error, refetch };
}
