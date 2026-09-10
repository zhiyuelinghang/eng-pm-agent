import { CUSTOM_REQUEST_BODY_KEY } from './model-parameters.ts';
import type { JSONSchema, JSONSchemaProperty } from '../api/types';

const EDITABLE_PARAMETERS = new Set(['thinking_enable', 'reasoning_effort']);

export function modelParameterFields(
	schema: JSONSchema | null | undefined,
): [string, JSONSchemaProperty][] {
	return Object.entries(schema?.properties ?? {}).filter(([key]) => EDITABLE_PARAMETERS.has(key));
}

export function modelParameterValues(parameters: Record<string, unknown>): Record<string, unknown> {
	return structuredClone(
		Object.fromEntries(
			Object.entries(parameters).filter(([key]) => key !== CUSTOM_REQUEST_BODY_KEY),
		),
	);
}

export function modelParameterOverrides(
	values: Record<string, unknown>,
	customBody: Record<string, unknown>,
): Record<string, unknown> {
	const overrides = Object.fromEntries(
		Object.entries(values).filter(
			([key, value]) =>
				key !== CUSTOM_REQUEST_BODY_KEY &&
				value !== undefined &&
				value !== null &&
				value !== '',
		),
	);
	if (Object.keys(customBody).length > 0) overrides[CUSTOM_REQUEST_BODY_KEY] = customBody;
	return structuredClone(overrides);
}

export function validateModelParameterValues(
	schema: JSONSchema | null | undefined,
	values: Record<string, unknown>,
): string | null {
	for (const [key, property] of modelParameterFields(schema)) {
		const value = values[key];
		if (value === undefined || value === null || value === '') continue;
		const variant = property.anyOf?.find((item) => item.type !== 'null') as
			| JSONSchemaProperty
			| undefined;
		const definition = { ...variant, ...property };
		if (definition.enum && !definition.enum.includes(value)) return key;
		if (definition.type === 'boolean' && typeof value !== 'boolean') return key;
		if (definition.type === 'number' || definition.type === 'integer') {
			if (typeof value !== 'number' || !Number.isFinite(value)) return key;
			if (definition.type === 'integer' && !Number.isInteger(value)) return key;
			if (definition.minimum !== undefined && value < definition.minimum) return key;
			if (definition.maximum !== undefined && value > definition.maximum) return key;
			if (definition.exclusiveMinimum !== undefined && value <= definition.exclusiveMinimum)
				return key;
			if (definition.exclusiveMaximum !== undefined && value >= definition.exclusiveMaximum)
				return key;
		}
	}
	return null;
}
