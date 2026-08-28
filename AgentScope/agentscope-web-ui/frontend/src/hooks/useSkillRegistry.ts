import { useCallback, useEffect, useState } from 'react';

import { skillRegistryApi } from '@/api';
import type { ManagedSkillInput, ManagedSkillPackage, ManagedSkillVersion } from '@/api';

export function useSkillRegistry(agentId: string | null) {
	const [packages, setPackages] = useState<ManagedSkillPackage[]>([]);
	const [loading, setLoading] = useState(false);
	const [uploading, setUploading] = useState(false);
	const [error, setError] = useState<Error | null>(null);

	const refetch = useCallback(async () => {
		if (!agentId) {
			setPackages([]);
			return;
		}
		setLoading(true);
		setError(null);
		try {
			setPackages(await skillRegistryApi.list(agentId));
		} catch (reason) {
			setError(reason as Error);
		} finally {
			setLoading(false);
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

	const uploadPackage = useCallback(
		async (file: File) => {
			setUploading(true);
			setError(null);
			try {
				await skillRegistryApi.upload(file);
				await refetch();
			} finally {
				setUploading(false);
			}
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
		(packageId: string): Promise<ManagedSkillVersion[]> =>
			skillRegistryApi.versions(packageId),
		[],
	);

	const downloadVersion = useCallback(
		(packageId: string, version: number) =>
			skillRegistryApi.downloadVersion(packageId, version),
		[],
	);

	return {
		packages,
		loading,
		uploading,
		error,
		refetch,
		createPackage,
		updatePackage,
		uploadPackage,
		removePackage,
		listVersions,
		downloadVersion,
	};
}
