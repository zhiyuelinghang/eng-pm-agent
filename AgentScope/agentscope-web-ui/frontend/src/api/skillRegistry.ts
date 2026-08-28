import { client } from './client';
import type {
	ManagedSkillInput,
	ManagedSkillPackage,
	ManagedSkillVersion,
} from './types';

export const skillRegistryApi = {
	list: (agentId: string) =>
		client.get<ManagedSkillPackage[]>('/skill-registry/', { agent_id: agentId }),

	create: (body: ManagedSkillInput) =>
		client.post<ManagedSkillPackage>('/skill-registry/', body),

	update: (packageId: string, body: ManagedSkillInput) =>
		client.put<ManagedSkillPackage>(
			`/skill-registry/${encodeURIComponent(packageId)}`,
			body,
		),

	upload: (file: File) => {
		const body = new FormData();
		body.append('file', file);
		return client.upload<ManagedSkillPackage>('/skill-registry/upload', body);
	},

	versions: (packageId: string) =>
		client.get<ManagedSkillVersion[]>(
			`/skill-registry/${encodeURIComponent(packageId)}/versions`,
		),

	downloadVersion: async (packageId: string, version: number) => {
		const response = await client.stream(
			`/skill-registry/${encodeURIComponent(packageId)}/versions/${version}/download`,
		);
		const url = URL.createObjectURL(await response.blob());
		try {
			const link = document.createElement('a');
			link.href = url;
			link.download = `${packageId}-v${version}.zip`;
			document.body.appendChild(link);
			link.click();
			link.remove();
		} finally {
			URL.revokeObjectURL(url);
		}
	},

	delete: (packageId: string) =>
		client.delete(`/skill-registry/${encodeURIComponent(packageId)}`),
};
