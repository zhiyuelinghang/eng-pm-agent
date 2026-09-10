import { useCallback, useEffect, useRef, useState } from 'react';

import { mcpRegistryApi } from '@/api';
import type { ManagedMCPPackage } from '@/api';

export function useMcpRegistry(agentId: string | null) {
	const [packages, setPackages] = useState<ManagedMCPPackage[]>([]);
	const [loading, setLoading] = useState(false);
	const [loadedAgentId, setLoadedAgentId] = useState<string | null>(null);
	const request = useRef(0);
	const [uploading, setUploading] = useState(false);
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
			const next = await mcpRegistryApi.list(agentId);
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
		loading: loading || (agentId !== null && loadedAgentId !== agentId),
		uploading,
		error,
		refetch,
		uploadPackage,
		removePackage,
	};
}
