import { client } from './client';
import type {
	PlatformAuditMessagesResponse,
	PlatformAuditTreeResponse,
} from './types';

export const platformAuditApi = {
	tree: () => client.get<PlatformAuditTreeResponse>('/platform-audit/tree'),
	messages: (sessionId: string) =>
		client.get<PlatformAuditMessagesResponse>(
			`/platform-audit/sessions/${sessionId}/messages`,
		),
};
