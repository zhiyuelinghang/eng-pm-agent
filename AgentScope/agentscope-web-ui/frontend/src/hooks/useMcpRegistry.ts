import { useCallback, useEffect, useState } from 'react';

import { mcpRegistryApi } from '@/api';
import type { ManagedMCPPackage } from '@/api';

export function useMcpRegistry(agentId: string | null) {
	const [packages, setPackages] = useState<ManagedMCPPackage[]>([]);
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
			setPackages(await mcpRegistryApi.list(agentId));
		} catch (reason) {
			setError(reason as Error);
		} finally {
			setLoading(false);
		}
	}, [agentId]);

	useEffect(() => {
		void refetch();
	}, [refetch]);

	const uploadPackage = useCallback(
		async (file: File) => {
			setUploading(true);
			setError(null);
			try {
				await mcpRegistryApi.upload(file);
				await refetch();
			} finally {
				setUploading(false);
			}
		},
		[refetch],
	);

	const removePackage = useCallback(
		async (packageId: string) => {
			await mcpRegistryApi.delete(packageId);
			await refetch();
		},
		[refetch],
	);

	return {
		packages,
		loading,
		uploading,
		error,
		refetch,
		uploadPackage,
		removePackage,
	};
}
