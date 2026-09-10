import type { JSONSchema, JSONSchemaProperty } from '../api/types';

const INTERNAL_FIELDS = new Set(['id', 'type', 'model_catalog']);

export function credentialFields(
	schema: JSONSchema | null | undefined,
): [string, JSONSchemaProperty][] {
	return Object.entries(schema?.properties ?? {}).filter(
		([key, property]) => !INTERNAL_FIELDS.has(key) && property.const === undefined,
	);
}

export function credentialFieldValue(data: Record<string, unknown>, key: string): string {
	return data[key] == null ? '' : String(data[key]);
}

export function credentialUpdateData(
	data: Record<string, unknown>,
	schema: JSONSchema | null | undefined,
	changes: Record<string, string>,
): Record<string, unknown> {
	const result = { ...data };
	delete result.id;
	// The server keeps its current catalogue when this key is omitted.
	delete result.model_catalog;
	for (const [key, property] of credentialFields(schema)) {
		if (!Object.hasOwn(changes, key)) continue;
		const nullable =
			property.type === 'null' || property.anyOf?.some((variant) => variant.type === 'null');
		result[key] = changes[key] === '' && nullable ? null : changes[key];
	}
	return result;
}
