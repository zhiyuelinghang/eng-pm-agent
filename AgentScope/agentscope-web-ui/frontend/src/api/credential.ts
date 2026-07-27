import { client } from './client';
import type {
	CreateCredentialRequest,
	CreateCredentialResponse,
	CredentialModelCatalogResponse,
	CredentialModelTestResponse,
	CredentialListResponse,
	CredentialView,
	CredentialSchemasResponse,
	UpdateCredentialRequest,
	UpdateCredentialModelCatalogRequest,
	TestCredentialModelRequest,
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

	testModel: (credentialId: string, body: TestCredentialModelRequest) =>
		client.post<CredentialModelTestResponse>(
			`/credential/${encodeURIComponent(credentialId)}/models/test`,
			body,
		),

	probeEmbeddingModel: (credentialId: string, body: TestCredentialModelRequest) =>
		client.post<CredentialModelTestResponse>(
			`/credential/${encodeURIComponent(credentialId)}/models/embedding/probe`,
			body,
		),

	delete: (credentialId: string) => client.delete(`/credential/${credentialId}`),
};
