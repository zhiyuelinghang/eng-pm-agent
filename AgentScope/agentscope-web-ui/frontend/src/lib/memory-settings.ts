import type { ChatModelConfig, MemorySettings, UpdateMemorySettingsRequest } from '../api/types';

export const MEMORY_SETTINGS_KEYS = [
	'learning_enabled',
	'learning_model_config',
	'learning_interactions_enabled',
	'learning_business_events_enabled',
	'group_learning_enabled',
	'compression_model_config',
] as const;

export type MemorySettingsKey = (typeof MEMORY_SETTINGS_KEYS)[number];
export type ModelReference = Pick<ChatModelConfig, 'type' | 'credential_id' | 'model'>;
export type MemoryValidationError = {
	field: 'learning_model_config' | 'compression_model_config' | 'learning_sources';
	code: 'model_required' | 'model_unavailable' | 'source_required';
};

/** Exact public contract: never echo internal policy fields from a response. */
export function pickMemorySettings(value: MemorySettings): MemorySettings {
	return Object.fromEntries(
		MEMORY_SETTINGS_KEYS.map((key) => [key, value[key]]),
	) as unknown as MemorySettings;
}

function canonical(value: unknown): unknown {
	if (Array.isArray(value)) return value.map(canonical);
	if (value !== null && typeof value === 'object') {
		return Object.fromEntries(
			Object.entries(value)
				.sort(([a], [b]) => a.localeCompare(b))
				.map(([key, item]) => [key, canonical(item)]),
		);
	}
	return value;
}

export function sameMemoryValue(a: unknown, b: unknown): boolean {
	return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
}

export function isAvailableMemoryModel(
	model: ChatModelConfig,
	available: ModelReference[],
): boolean {
	return available.some(
		(item) =>
			item.type === model.type &&
			item.credential_id === model.credential_id &&
			item.model === model.model,
	);
}

export function validateMemorySettings(
	value: MemorySettings,
	available: ModelReference[],
): MemoryValidationError[] {
	const errors: MemoryValidationError[] = [];
	if (value.learning_enabled && !value.learning_model_config) {
		errors.push({ field: 'learning_model_config', code: 'model_required' });
	}
	if (
		value.learning_enabled &&
		!value.learning_interactions_enabled &&
		!value.learning_business_events_enabled &&
		!value.group_learning_enabled
	) {
		errors.push({ field: 'learning_sources', code: 'source_required' });
	}
	for (const field of ['learning_model_config', 'compression_model_config'] as const) {
		if (value[field] && !isAvailableMemoryModel(value[field], available)) {
			errors.push({ field, code: 'model_unavailable' });
		}
	}
	return errors;
}

export function memorySettingsRequest(
	settings: MemorySettings,
	revision: number,
): UpdateMemorySettingsRequest {
	if (!Number.isInteger(revision) || revision < 0)
		throw new Error('A valid settings revision is required.');
	const payload = pickMemorySettings(settings);
	for (const key of MEMORY_SETTINGS_KEYS) {
		if (key.endsWith('_config')) {
			if (payload[key] !== null && (!payload[key] || typeof payload[key] !== 'object'))
				throw new Error('Memory model settings are incomplete.');
		} else if (typeof payload[key] !== 'boolean') {
			throw new Error('Memory settings are incomplete.');
		}
	}
	return { settings: payload, expected_revision: revision };
}

export function memorySettingsChanges(
	base: MemorySettings,
	local: MemorySettings,
	remote: MemorySettings,
) {
	return MEMORY_SETTINGS_KEYS.flatMap((key) => {
		const localChanged = !sameMemoryValue(base[key], local[key]);
		const remoteChanged = !sameMemoryValue(base[key], remote[key]);
		if (!localChanged && !remoteChanged) return [];
		return [
			{
				key,
				localChanged,
				remoteChanged,
				conflict:
					localChanged && remoteChanged && !sameMemoryValue(local[key], remote[key]),
			},
		];
	});
}

/** Rebase only with explicit choices for fields changed differently on both sides. */
export function mergeMemorySettings(
	base: MemorySettings,
	local: MemorySettings,
	remote: MemorySettings,
	choices: Partial<Record<MemorySettingsKey, 'local' | 'remote'>>,
): MemorySettings {
	const merged = pickMemorySettings(remote);
	for (const change of memorySettingsChanges(base, local, remote)) {
		if (change.conflict && !choices[change.key])
			throw new Error(`Choose which value to keep for ${change.key}.`);
		const useLocal = change.conflict ? choices[change.key] === 'local' : change.localChanged;
		if (useLocal) Object.assign(merged, { [change.key]: local[change.key] });
	}
	return merged;
}
