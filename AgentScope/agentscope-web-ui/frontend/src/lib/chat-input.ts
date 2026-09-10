import type { ContentBlock } from '@agentscope-ai/agentscope/message';

import type { ChatModelConfig, ModelCard } from '../api/types';
import type { CredentialWithModels } from '../hooks/useAvailableModels';

type ModelGroups = Record<string, CredentialWithModels[]>;

export function availableChatModel(
	groups: ModelGroups,
	config: ChatModelConfig | null | undefined,
): ModelCard | null {
	if (!config) return null;
	return (
		groups[config.type]
			?.find(({ credential }) => credential.id === config.credential_id)
			?.models.find(({ name }) => name === config.model) ?? null
	);
}

export function firstAvailableChatModel(groups: ModelGroups): ChatModelConfig | null {
	for (const [type, entries] of Object.entries(groups)) {
		for (const { credential, models } of entries) {
			const model = models.find(({ name }) => Boolean(name));
			if (model)
				return { type, credential_id: credential.id, model: model.name, parameters: {} };
		}
	}
	return null;
}

export function resolveSessionChatModel(
	groups: ModelGroups,
	current: ChatModelConfig | null | undefined,
): ChatModelConfig | null {
	return availableChatModel(groups, current) ? current! : firstAvailableChatModel(groups);
}

const ATTACHMENT_MEDIA_TYPES: Record<string, string> = {
	png: 'image/png',
	jpg: 'image/jpeg',
	jpeg: 'image/jpeg',
	webp: 'image/webp',
	gif: 'image/gif',
	bmp: 'image/bmp',
	tif: 'image/tiff',
	tiff: 'image/tiff',
	jp2: 'image/jp2',
	txt: 'text/plain',
	md: 'text/markdown',
	csv: 'text/csv',
	pdf: 'application/pdf',
	xls: 'application/vnd.ms-excel',
	xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
	docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
	pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
};

export function chatAttachmentBlock(
	file: Pick<File, 'name' | 'type'>,
	dataUrl: string,
	id: string,
): ContentBlock {
	const suppliedType = file.type.trim().toLowerCase();
	const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
	const mediaType =
		suppliedType && suppliedType !== 'application/octet-stream'
			? suppliedType
			: (ATTACHMENT_MEDIA_TYPES[extension] ?? 'application/octet-stream');
	return {
		id,
		type: 'data',
		name: file.name,
		source: { type: 'base64', media_type: mediaType, data: dataUrl.split(',', 2)[1] ?? '' },
	};
}
