import { client } from './client';
import type {
	ManagedMCPPackage,
	ManagedMCPVersion,
	ProjectInitializationValidationMCPConfig,
} from './types';

export const mcpRegistryApi = {
	list: (agentId: string) =>
		client.get<ManagedMCPPackage[]>('/mcp-registry/', { agent_id: agentId }),

	upload: (file: File) => {
		const body = new FormData();
		body.append('file', file);
		return client.upload<ManagedMCPPackage>('/mcp-registry/upload', body);
	},

	getInitializationValidationConfig: () =>
		client.get<ProjectInitializationValidationMCPConfig>(
			'/mcp-registry/platform/project-initialization-validation',
		),

	uploadInitializationValidationVersion: (file: File) => {
		const body = new FormData();
		body.append('file', file);
		return client.upload<ManagedMCPVersion>(
			'/mcp-registry/platform/project-initialization-validation/upload',
			body,
		);
	},

	downloadInitializationValidationVersion: async (
		packageId: string,
		version: string,
	) => {
		const packagePart = encodeURIComponent(packageId);
		const versionPart = encodeURIComponent(version);
		const response = await client.stream(
			`/mcp-registry/platform/project-initialization-validation/${packagePart}/${versionPart}/download`,
		);
		const url = URL.createObjectURL(await response.blob());
		try {
			const link = document.createElement('a');
			link.href = url;
			link.download = `${packageId}-${version}.zip`;
			document.body.appendChild(link);
			link.click();
			link.remove();
		} finally {
			URL.revokeObjectURL(url);
		}
	},

	deleteInitializationValidationVersion: (
		packageId: string,
		version: string,
	) =>
		client.delete(
			`/mcp-registry/platform/project-initialization-validation/${encodeURIComponent(packageId)}/${encodeURIComponent(version)}`,
		),

	delete: (packageId: string) => client.delete(`/mcp-registry/${packageId}`),
};
