import { useCallback, useEffect, useRef, useState } from 'react';

import { skillRegistryApi } from '@/api';
import type { ManagedSkillInput, ManagedSkillPackage, ManagedSkillVersion } from '@/api';

export function useSkillRegistry(agentId: string | null) {
	const [packages, setPackages] = useState<ManagedSkillPackage[]>([]);
	const [loading, setLoading] = useState(false);
	const [loadedAgentId, setLoadedAgentId] = useState<string | null>(null);
	const request = useRef(0);
	const [error, setError] = useState<Error | null>(null);

	const refetch = useCallback(async () => {
		const ticket = ++request.current;
		if (!agentId) {
			setPackages([]);
			setLoadedAgentId(null);
			setLoading(false);
			return;
		}
		setLoading(true);
		setError(null);
		try {
			const next = await skillRegistryApi.list(agentId);
			if (ticket === request.current) setPackages(next);
		} catch (reason) {
			if (ticket === request.current) setError(reason as Error);
		} finally {
			if (ticket === request.current) {
				setLoadedAgentId(agentId);
				setLoading(false);
			}
		}
	}, [agentId]);

	useEffect(() => {
		void refetch();
	}, [refetch]);

	const createPackage = useCallback(
		async (input: ManagedSkillInput) => {
			await skillRegistryApi.create(input);
			await refetch();
		},
		[refetch],
	);

	const updatePackage = useCallback(
		async (packageId: string, input: ManagedSkillInput) => {
			await skillRegistryApi.update(packageId, input);
			await refetch();
		},
		[refetch],
	);

	const removePackage = useCallback(
		async (packageId: string) => {
			await skillRegistryApi.delete(packageId);
			await refetch();
		},
		[refetch],
	);

	const listVersions = useCallback(
		(packageId: string): Promise<ManagedSkillVersion[]> => skillRegistryApi.versions(packageId),
		[],
	);

	const downloadVersion = useCallback(
		(packageId: string, version: number) =>
			skillRegistryApi.downloadVersion(packageId, version),
		[],
	);

	return {
		packages,
		loading: loading || (agentId !== null && loadedAgentId !== agentId),
		error,
		refetch,
		createPackage,
		updatePackage,
		removePackage,
		listVersions,
		downloadVersion,
	};
}
