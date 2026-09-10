import { useState, useEffect, useCallback } from 'react';

import { workspaceApi } from '@/api';
import type { WorkspaceTool } from '@/api';

export function useWorkspace(agentId: string | null, sessionId: string | null) {
	const [tools, setTools] = useState<WorkspaceTool[]>([]);
	const [toolsLoading, setToolsLoading] = useState(false);
	const [error, setError] = useState<Error | null>(null);

	const refetchTools = useCallback(async () => {
		if (!agentId) {
			setTools([]);
			return;
		}
		setToolsLoading(true);
		setError(null);
		try {
			setTools(await workspaceApi.tool.list(agentId, sessionId));
		} catch (e) {
			setError(e as Error);
		} finally {
			setToolsLoading(false);
		}
	}, [agentId, sessionId]);

	useEffect(() => {
		void refetchTools();
	}, [refetchTools]);

	return {
		error,
		tools,
		toolsLoading,
		refetchTools,
	};
}
