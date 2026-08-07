import { client } from './client';
import type { ManagedMCPPackage } from './types';

export const mcpRegistryApi = {
	list: (agentId: string) =>
		client.get<ManagedMCPPackage[]>('/mcp-registry/', { agent_id: agentId }),

	upload: (file: File) => {
		const body = new FormData();
		body.append('file', file);
		return client.upload<ManagedMCPPackage>('/mcp-registry/upload', body);
	},

	delete: (packageId: string) => client.delete(`/mcp-registry/${packageId}`),
};
