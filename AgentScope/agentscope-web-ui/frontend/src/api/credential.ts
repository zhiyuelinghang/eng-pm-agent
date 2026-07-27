import { client } from './client';
import type {
	CreateCredentialRequest,
	CreateCredentialResponse,
	CredentialModelCatalogResponse,
	CredentialListResponse,
	CredentialView,
	CredentialSchemasResponse,
	UpdateCredentialRequest,
	UpdateCredentialModelCatalogRequest,
} from './types';

export const credentialApi = {
	list: () => client.get<CredentialListResponse>('/credential/'),

	schemas: () => client.get<CredentialSchemasResponse>('/credential/schemas'),

	create: (body: CreateCredentialRequest) =>
		client.post<CreateCredentialResponse>('/credential/', body),

	update: (credentialId: string, body: UpdateCredentialRequest) =>
		client.patch<CredentialView>(`/credential/${credentialId}`, body),

	models: (credentialId: string) =>
		client.get<CredentialModelCatalogResponse>(
			`/credential/${encodeURIComponent(credentialId)}/models`,
		),

	discoverModels: (credentialId: string, silent = false) =>
		client.post<CredentialModelCatalogResponse>(
			`/credential/${encodeURIComponent(credentialId)}/models/discover`,
			undefined,
			undefined,
			{ silent },
		),

	updateModels: (credentialId: string, body: UpdateCredentialModelCatalogRequest) =>
		client.patch<CredentialModelCatalogResponse>(
			`/credential/${encodeURIComponent(credentialId)}/models`,
			body,
		),

	delete: (credentialId: string) => client.delete(`/credential/${credentialId}`),
};
